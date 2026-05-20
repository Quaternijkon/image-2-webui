from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable

from app.core.config import AppConfig
from app.core.errors import ImageBatchError, classify_exception
from app.core.event_protocol import EventProtocol
from app.core.manifest_store import ManifestStore, sanitize_record
from app.core.models import PlannedJob, TaskPlan
from app.core.openai_image_client import CompletedImage, ImageClient, PartialImage
from app.core.output_writer import OutputWriter


EventSink = Callable[[str], None]


class _ControlRequested(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


class BatchEngine:
    def __init__(
        self,
        config: AppConfig,
        planned_job: PlannedJob,
        client: ImageClient,
        *,
        event_sink: EventSink | None = None,
        writer: OutputWriter | None = None,
        manifest_store: ManifestStore | None = None,
        resume: bool = False,
        retry_backoff_seconds: float = 0.25,
        control_path: Path | None = None,
    ) -> None:
        self.config = config
        self.planned_job = planned_job
        self.client = client
        self.event_sink = event_sink
        self.writer = writer or OutputWriter(output_root=planned_job.job.root)
        self.manifest = manifest_store or ManifestStore(planned_job.job.manifest_path)
        self.resume = resume
        self.retry_backoff_seconds = retry_backoff_seconds
        self.control_path = control_path or planned_job.job.root / "job.control.json"
        self._stop_requested = False
        self.summary = {
            "total": len(planned_job.tasks),
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "paused": 0,
            "canceled": 0,
            "stopped": 0,
        }

    async def run(self) -> dict[str, int]:
        self._ensure_layout()
        self._clear_control_state()
        try:
            self._emit("job_started", job_id=self.planned_job.job.job_id, total_tasks=len(self.planned_job.tasks))
            runnable_tasks = self._select_runnable_tasks()

            semaphore = asyncio.Semaphore(self.config.execution.concurrency)
            await asyncio.gather(*(self._run_with_semaphore(semaphore, task) for task in runnable_tasks))

            self._write_summary()
            self._emit("job_completed", **self.summary)
            return dict(self.summary)
        finally:
            self._clear_control_state()

    def _select_runnable_tasks(self) -> list[TaskPlan]:
        if not self.resume:
            return list(self.planned_job.tasks)

        resume_ids = set(
            self.manifest.tasks_needing_resume([task.task_id for task in self.planned_job.tasks], retry_failed=True)
        )
        runnable: list[TaskPlan] = []
        latest = self.manifest.load_latest_by_task()
        for task in self.planned_job.tasks:
            if task.task_id in resume_ids:
                runnable.append(task)
            elif latest.get(task.task_id, {}).get("status") in {"succeeded", "skipped"}:
                self.summary["skipped"] += 1
        return runnable

    async def _run_with_semaphore(self, semaphore: asyncio.Semaphore, task: TaskPlan) -> None:
        async with semaphore:
            await self._run_task(task)

    async def _run_task(self, task: TaskPlan) -> None:
        control_state = self._read_control_state()
        if control_state.get("cancel_requested") is True:
            self._record_terminal_state(task, "canceled")
            return
        if control_state.get("pause_requested") is True:
            self._record_terminal_state(task, "paused")
            return
        if self._stop_requested:
            self._record_terminal_state(task, "stopped")
            return
        if task.status == "validation_failed":
            self._record_failed(
                task,
                ImageBatchError("validation_failed", "task failed preflight validation"),
                0,
                issues=_task_issue_details(task),
            )
            return
        if task.output_plan and task.output_plan.should_skip:
            self.summary["skipped"] += 1
            self.manifest.append_task_record({"task_id": task.task_id, "status": "skipped"})
            return

        attempt = 0
        max_attempts = self.config.execution.max_retries + 1
        while attempt < max_attempts:
            attempt += 1
            self._emit("task_started", job_id=self.planned_job.job.job_id, task_id=task.task_id, attempt=attempt)
            self.manifest.append_task_record({"task_id": task.task_id, "status": "running", "attempt": attempt})
            try:
                results = await self._run_client_task(task)
                output_files: list[str] = []
                usage = None
                completed_seen = False
                for result in results:
                    if isinstance(result, PartialImage):
                        if self.config.image.save_partials:
                            partial_path = self.writer.write_partial(
                                task,
                                result.b64_json,
                                partial_index=result.index,
                                output_format=self.config.image.output_format,
                            )
                            self._emit(
                                "partial_saved",
                                task_id=task.task_id,
                                partial_index=result.index,
                                path=str(partial_path),
                            )
                    elif isinstance(result, CompletedImage):
                        final_path = self.writer.write_final(task, result.b64_json)
                        output_files.append(str(final_path))
                        usage = result.usage
                        completed_seen = True
                if not completed_seen:
                    raise ImageBatchError("invalid_response", "API response did not include a completed image")
                self.summary["succeeded"] += 1
                record = {
                    "task_id": task.task_id,
                    "status": "succeeded",
                    "attempt": attempt,
                    "output_files": output_files,
                }
                if usage is not None:
                    record["usage"] = usage
                self.manifest.append_task_record(record)
                self._emit(
                    "task_succeeded",
                    job_id=self.planned_job.job.job_id,
                    task_id=task.task_id,
                    output_files=output_files,
                )
                return
            except _ControlRequested as control:
                self._record_terminal_state(task, control.status)
                return
            except Exception as exc:
                error = classify_exception(exc)
                if error.retryable and attempt < max_attempts:
                    self._record_retry_scheduled(task, error, attempt)
                    if self._terminal_control_recorded(task):
                        return
                    await asyncio.sleep(self.retry_backoff_seconds * attempt)
                    continue
                self._record_failed(task, error, attempt)
                return

    async def _run_client_task(self, task: TaskPlan) -> ImageClientResult:
        client_task = asyncio.create_task(self.client.run_task(task))
        control_task = asyncio.create_task(self._wait_for_terminal_control())
        try:
            done, _ = await asyncio.wait(
                {client_task, control_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if control_task in done:
                status = control_task.result()
                if not client_task.done():
                    client_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await client_task
                raise _ControlRequested(status)
            return await client_task
        finally:
            control_task.cancel()
            if not client_task.done():
                client_task.cancel()
                with suppress(asyncio.CancelledError):
                    await client_task

    async def _wait_for_terminal_control(self) -> str:
        while True:
            control_state = self._read_control_state()
            if control_state.get("cancel_requested") is True:
                return "canceled"
            if control_state.get("pause_requested") is True:
                return "paused"
            await asyncio.sleep(0.25)

    def _record_retry_scheduled(self, task: TaskPlan, error: ImageBatchError, attempt: int) -> None:
        retry_message = f"retry scheduled: {error.message}"
        self.manifest.append_task_record(
            {
                "task_id": task.task_id,
                "status": "failed",
                "attempt": attempt,
                "error_code": error.code,
                "message": retry_message,
            }
        )
        self._emit(
            "task_failed",
            task_id=task.task_id,
            error_code=error.code,
            message=retry_message,
            attempt=attempt,
        )

    def _record_failed(
        self,
        task: TaskPlan,
        error: ImageBatchError,
        attempt: int,
        *,
        issues: list[dict[str, Any]] | None = None,
    ) -> None:
        self.summary["failed"] += 1
        if self.config.execution.failure_policy == "stop":
            self._stop_requested = True
        record = {
            "task_id": task.task_id,
            "status": "failed",
            "attempt": attempt,
            "error_code": error.code,
            "message": error.message,
        }
        if issues:
            record["issues"] = issues
        self.manifest.append_task_record(record)
        event_fields: dict[str, Any] = {
            "task_id": task.task_id,
            "error_code": error.code,
            "message": error.message,
            "attempt": attempt,
        }
        if issues:
            event_fields["issues"] = issues
        self._emit("task_failed", **event_fields)

    def _record_terminal_state(self, task: TaskPlan, status: str) -> None:
        self.summary[status] += 1
        self.manifest.append_task_record({"task_id": task.task_id, "status": status})
        self._emit(f"task_{status}", job_id=self.planned_job.job.job_id, task_id=task.task_id)

    def _terminal_control_recorded(self, task: TaskPlan) -> bool:
        control_state = self._read_control_state()
        if control_state.get("cancel_requested") is True:
            self._record_terminal_state(task, "canceled")
            return True
        if control_state.get("pause_requested") is True:
            self._record_terminal_state(task, "paused")
            return True
        return False

    def _emit(self, event: str, **fields: object) -> None:
        line = EventProtocol.serialize(event, **fields)
        if self.event_sink is not None:
            self.event_sink(line)
        if self.planned_job.job.events_jsonl_path:
            self.planned_job.job.events_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with self.planned_job.job.events_jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(line)

    def _read_control_state(self) -> dict[str, Any]:
        if not self.control_path.exists():
            return {}
        try:
            payload = json.loads(self.control_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    def _clear_control_state(self) -> None:
        try:
            self.control_path.unlink(missing_ok=True)
        except OSError:
            return

    def _write_summary(self) -> None:
        _write_json(self.planned_job.job.summary_path, self.summary)

    def _ensure_layout(self) -> None:
        for path in [
            self.planned_job.job.root,
            self.planned_job.job.final_dir,
            self.planned_job.job.partials_dir,
            self.planned_job.job.failed_dir,
            self.planned_job.job.thumbnails_dir,
            self.planned_job.job.logs_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, value: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sanitize_record(value), sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _task_issue_details(task: TaskPlan) -> list[dict[str, Any]]:
    issues = getattr(getattr(task, "input_image", None), "issues", None) or []
    details: list[dict[str, Any]] = []
    for issue in issues:
        if hasattr(issue, "model_dump"):
            details.append(issue.model_dump(mode="json"))
        elif isinstance(issue, dict):
            details.append(issue)
        else:
            details.append(
                {
                    "code": getattr(issue, "code", "validation_failed"),
                    "message": getattr(issue, "message", str(issue)),
                }
            )
    return details


__all__ = ["BatchEngine"]
