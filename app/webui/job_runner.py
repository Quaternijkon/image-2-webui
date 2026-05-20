from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from threading import Lock, Thread
from typing import Callable, Iterable

from app.core.batch_engine import BatchEngine
from app.core.config import AppConfig
from app.core.connectivity_check import (
    ConnectivityCheckResult,
    check_api_connectivity,
    format_connectivity_event,
)
from app.core.cost_estimator import CostEstimate, CostEstimator
from app.core.event_protocol import EventProtocol
from app.core.manifest_store import ManifestStore, sanitize_record
from app.core.models import PlannedJob
from app.core.openai_image_client import CompletedImage, ImageClient, OpenAIImageClient, PartialImage
from app.core.task_planner import TaskPlanner
from app.webui.state import WebFormState


ClientFactory = Callable[[object], ImageClient]
ConnectivityChecker = Callable[[AppConfig], ConnectivityCheckResult]


@dataclass
class WebJobSnapshot:
    status: str
    job_root: Path
    summary: dict[str, int]
    estimate: CostEstimate
    command_preview: str = ""
    event_log: list[str] = field(default_factory=list)
    task_rows: list[dict[str, str]] = field(default_factory=list)
    output_files: list[Path] = field(default_factory=list)
    current_preview_b64: str | None = None
    actual_usage: dict[str, object] | None = None


class WebJobRunner:
    def __init__(
        self,
        *,
        client_factory: ClientFactory | None = None,
        connectivity_checker: ConnectivityChecker | None = None,
    ) -> None:
        self.client_factory = client_factory or (lambda config: OpenAIImageClient(config))
        self.connectivity_checker = connectivity_checker or (
            lambda config: check_api_connectivity(config, timeout_seconds=5, endpoint_probe=True)
        )
        self._control_lock = Lock()
        self._active_control_path: Path | None = None

    def dry_run(self, state: WebFormState) -> WebJobSnapshot:
        config = state.build_config()
        planned = TaskPlanner(config).build()
        estimate = CostEstimator(config).estimate(planned)
        connectivity = self.connectivity_checker(config)
        return _snapshot(
            status="dry_run",
            planned=planned,
            estimate=estimate,
            summary={"total_tasks": len(planned.tasks), "issues": len(planned.issues)},
            event_log=[format_connectivity_event(connectivity)],
        )

    def run(self, state: WebFormState) -> Iterable[WebJobSnapshot]:
        config = state.build_config()
        planned = TaskPlanner(config).build()
        estimate = CostEstimator(config).estimate(planned)
        tracker = _RunTracker(planned=planned, estimate=estimate)
        self._set_active_control_path(planned.job.root / "job.control.json")
        yield tracker.snapshot("running")

        event_queue: Queue[object] = Queue()
        done_marker = object()
        errors: list[BaseException] = []

        def event_sink(line: str) -> None:
            tracker.handle_event_line(line)
            event_queue.put(line)

        def run_engine() -> None:
            try:
                client = _PreviewingClient(self.client_factory(config), tracker)
                tracker.summary = asyncio.run(
                    BatchEngine(
                        config,
                        planned,
                        client,
                        event_sink=event_sink,
                    ).run()
                )
            except BaseException as exc:
                errors.append(exc)
            finally:
                event_queue.put(done_marker)

        thread = Thread(target=run_engine, name="webui-batch-engine", daemon=True)
        thread.start()
        try:
            while True:
                event = event_queue.get()
                if event is done_marker:
                    break
                yield tracker.snapshot("running")
            thread.join()
            if errors:
                raise errors[0]
            yield tracker.snapshot("completed")
        finally:
            self._clear_active_control_path(planned.job.root / "job.control.json")

    def request_pause(self) -> Path:
        return self._write_control({"pause_requested": True})

    def request_cancel(self) -> Path:
        return self._write_control({"cancel_requested": True})

    def _set_active_control_path(self, path: Path) -> None:
        with self._control_lock:
            self._active_control_path = path

    def _clear_active_control_path(self, path: Path) -> None:
        with self._control_lock:
            if self._active_control_path == path:
                self._active_control_path = None

    def _write_control(self, payload: dict[str, bool]) -> Path:
        with self._control_lock:
            control_path = self._active_control_path
        if control_path is None:
            raise RuntimeError("No active WebUI job is available for control.")
        control_path.parent.mkdir(parents=True, exist_ok=True)
        control_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return control_path


class _PreviewingClient:
    def __init__(self, client: ImageClient, tracker: "_RunTracker") -> None:
        self.client = client
        self.tracker = tracker

    async def run_task(self, task):
        results = await self.client.run_task(task)
        for result in results:
            if isinstance(result, PartialImage):
                self.tracker.current_preview_b64 = result.b64_json
            elif isinstance(result, CompletedImage):
                self.tracker.actual_usage = result.usage
        return results


@dataclass
class _RunTracker:
    planned: PlannedJob
    estimate: CostEstimate
    summary: dict[str, int] = field(default_factory=dict)
    event_log: list[str] = field(default_factory=list)
    current_preview_b64: str | None = None
    actual_usage: dict[str, object] | None = None

    def handle_event_line(self, line: str) -> None:
        self.event_log.append(line.rstrip("\n"))

    def snapshot(self, status: str) -> WebJobSnapshot:
        manifest = ManifestStore(self.planned.job.manifest_path)
        records = manifest.load_latest_by_task()
        output_files: list[Path] = []
        task_rows: list[dict[str, str]] = []
        actual_usage = self.actual_usage
        for task in self.planned.tasks:
            record = records.get(task.task_id, {})
            output_files.extend(Path(path) for path in record.get("output_files", []) or [])
            if record.get("usage"):
                actual_usage = record["usage"]
            task_rows.append(
                {
                    "task_id": task.task_id,
                    "status": str(record.get("status", task.status)),
                    "message": str(record.get("message", "")),
                }
            )

        return _snapshot(
            status=status,
            planned=self.planned,
            estimate=self.estimate,
            summary=self.summary or {"total_tasks": len(self.planned.tasks), "issues": len(self.planned.issues)},
            event_log=list(self.event_log),
            task_rows=task_rows,
            output_files=output_files,
            current_preview_b64=self.current_preview_b64,
            actual_usage=actual_usage,
        )


def _snapshot(
    *,
    status: str,
    planned: PlannedJob,
    estimate: CostEstimate,
    summary: dict[str, int],
    event_log: list[str] | None = None,
    task_rows: list[dict[str, str]] | None = None,
    output_files: list[Path] | None = None,
    current_preview_b64: str | None = None,
    actual_usage: dict[str, object] | None = None,
) -> WebJobSnapshot:
    command_preview = ""
    if planned.job.command_path.exists():
        command_preview = planned.job.command_path.read_text(encoding="utf-8")
    return WebJobSnapshot(
        status=status,
        job_root=planned.job.root,
        summary=sanitize_record(summary),
        estimate=estimate,
        command_preview=command_preview,
        event_log=event_log or [],
        task_rows=task_rows or _initial_task_rows(planned),
        output_files=output_files or [],
        current_preview_b64=current_preview_b64,
        actual_usage=sanitize_record(actual_usage) if actual_usage else None,
    )


def _initial_task_rows(planned: PlannedJob) -> list[dict[str, str]]:
    return [
        {"task_id": task.task_id, "status": task.status, "message": ""}
        for task in planned.tasks
    ]


def snapshot_to_log_text(snapshot: WebJobSnapshot) -> str:
    if not snapshot.event_log:
        return ""
    parsed: list[dict[str, object]] = []
    for line in snapshot.event_log:
        try:
            parsed.append(EventProtocol.parse_line(line))
        except Exception:
            parsed.append({"event": "raw", "line": line})
    return "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) for record in parsed)


__all__ = ["WebJobRunner", "WebJobSnapshot", "snapshot_to_log_text"]
