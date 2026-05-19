import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.command_builder import CommandBuilder
from app.core.config import AppConfig
from app.core.manifest_store import sanitize_record
from app.core.models import JobLayout, OutputPlan, TaskPlan
from app.core.prompt_renderer import PromptRenderer

WINDOWS_INVALID_FILENAME_CHARS = set('<>:"/\\|?*')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class OutputPlanningError(ValueError):
    pass


class OutputPlanner:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def create_job_layout(self) -> JobLayout:
        output_root = self.config.output.output_dir or Path.cwd() / "output"
        if self.config.output.job_subdir_enabled or self.config.execution.overwrite_policy == "new_job_dir":
            job_id = _unique_job_id(output_root)
            root = output_root / job_id
        else:
            root = output_root
            job_id = root.name or "job-root"

        layout = JobLayout(
            job_id=job_id,
            root=root,
            final_dir=root / "final",
            partials_dir=root / "partials",
            logs_dir=root / "logs",
            app_log_path=root / "logs" / "app.log",
            events_jsonl_path=root / "logs" / "events.jsonl",
            errors_jsonl_path=root / "logs" / "errors.jsonl",
            failed_dir=root / "failed",
            thumbnails_dir=root / "thumbnails",
            manifest_path=root / "manifest.jsonl",
            summary_path=root / "summary.json",
            config_snapshot_path=root / "config.snapshot.json",
            command_path=root / "command.ps1",
        )

        directories = [
            layout.root,
            layout.final_dir,
            layout.partials_dir,
            layout.failed_dir,
            layout.thumbnails_dir,
        ]
        if self.config.output.save_logs:
            directories.append(layout.logs_dir)
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
        if self.config.output.save_logs:
            layout.app_log_path.touch(exist_ok=True)
            layout.events_jsonl_path.touch(exist_ok=True)
            layout.errors_jsonl_path.touch(exist_ok=True)

        if self.config.output.save_config_snapshot:
            _write_json(layout.config_snapshot_path, _sanitized_config(self.config))
        if self.config.output.save_manifest:
            layout.manifest_path.touch(exist_ok=True)
        _write_json(layout.summary_path, {"total": 0, "succeeded": 0, "failed": 0, "skipped": 0})
        layout.command_path.write_text(
            CommandBuilder(self.config).build_powershell_command(
                config_path=layout.config_snapshot_path,
                input_dir=self.config.input.input_dir,
                output_dir=layout.root,
                concurrency=self.config.execution.concurrency,
                events_jsonl=True,
            ),
            encoding="utf-8",
        )
        return layout

    def plan_variant_output(
        self,
        job: JobLayout,
        task: TaskPlan,
        *,
        variant: int,
        reserved_paths: set[Path] | None = None,
    ) -> OutputPlan:
        stem = _task_stem(task)
        extension = self.config.image.output_format.lower().lstrip(".")
        context = {
            "stem": stem,
            "index": _task_index(task.task_id),
            "variant": f"v{variant}",
            "quality": self.config.image.quality,
            "size": self.config.image.size,
            "date": datetime.now().strftime("%Y%m%d"),
            "hash": _task_hash(task),
            "ext": extension,
        }
        filename = PromptRenderer(variables_enabled=True, context=context).render(
            self.config.output.filename_template
        )
        if not filename or filename.startswith("."):
            raise OutputPlanningError("unsafe output filename: empty name")
        if Path(filename).suffix == "":
            filename = f"{filename}.{extension}"
        _validate_filename(filename)
        final_path = job.final_dir / filename
        try:
            final_path.resolve().relative_to(job.final_dir.resolve())
        except ValueError as exc:
            raise OutputPlanningError("unsafe output filename: outside final directory") from exc
        policy = self.config.execution.overwrite_policy
        should_skip = False

        reserved_paths = reserved_paths or set()
        if final_path in reserved_paths:
            final_path = _append_counter(final_path, reserved_paths=reserved_paths)
        elif final_path.exists():
            if policy == "skip_existing":
                should_skip = True
            elif policy == "append_counter":
                final_path = _append_counter(final_path, reserved_paths=reserved_paths)

        return OutputPlan(
            final_path=final_path,
            partials_dir=job.partials_dir / task.task_id,
            failed_dir=job.failed_dir,
            thumbnails_dir=job.thumbnails_dir,
            should_skip=should_skip,
            overwrite_policy=policy,
        )


def _unique_job_id(output_root: Path) -> str:
    base = datetime.now().strftime("job-%Y%m%d-%H%M%S")
    candidate = base
    counter = 1
    while (output_root / candidate).exists():
        candidate = f"{base}-{counter:03d}"
        counter += 1
    return candidate


def _sanitized_config(config: AppConfig) -> dict[str, Any]:
    return sanitize_record(config.model_dump(mode="json", exclude_none=True))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _task_stem(task: TaskPlan) -> str:
    if task.source_paths:
        return task.source_paths[0].stem
    if task.mode == "generate":
        return "generate"
    return task.task_id


def _task_index(task_id: str) -> str:
    suffix = task_id.rsplit("-", 1)[-1]
    try:
        return f"{int(suffix):06d}"
    except ValueError:
        return task_id


def _task_hash(task: TaskPlan) -> str:
    digest = hashlib.sha256()
    digest.update(task.task_id.encode("utf-8"))
    for path in task.source_paths:
        digest.update(str(path).encode("utf-8"))
    digest.update(task.rendered_prompt.encode("utf-8"))
    return digest.hexdigest()[:8]


def _append_counter(path: Path, *, reserved_paths: set[Path] | None = None) -> Path:
    reserved_paths = reserved_paths or set()
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists() and candidate not in reserved_paths:
            return candidate
        counter += 1


def _validate_filename(filename: str) -> None:
    path = Path(filename)
    stem = path.stem
    if not filename or filename in {".", ".."}:
        raise OutputPlanningError("unsafe output filename: empty name")
    if path.is_absolute() or path.name != filename or ".." in path.parts:
        raise OutputPlanningError("unsafe output filename: path components are not allowed")
    if any(char in WINDOWS_INVALID_FILENAME_CHARS for char in filename):
        raise OutputPlanningError("unsafe output filename: invalid character")
    first_name_segment = path.name.split(".", 1)[0].upper()
    if not stem or first_name_segment in WINDOWS_RESERVED_NAMES:
        raise OutputPlanningError("unsafe output filename: reserved or empty name")


__all__ = ["OutputPlanner", "OutputPlanningError"]
