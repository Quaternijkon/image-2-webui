from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class CoreModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)


class PreflightIssue(CoreModel):
    code: str
    message: str
    path: Optional[Path] = None
    task_id: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)


class InputImage(CoreModel):
    path: Path
    width: int
    height: int
    format: str
    mask_path: Optional[Path] = None
    validation_status: Literal["valid", "validation_failed"] = "valid"
    issues: list[PreflightIssue] = Field(default_factory=list)


class OutputPlan(CoreModel):
    final_path: Path
    partials_dir: Path
    failed_dir: Path
    thumbnails_dir: Path
    should_skip: bool = False
    overwrite_policy: str = "skip_existing"


class TaskPlan(CoreModel):
    task_id: str
    mode: str
    source_paths: list[Path] = Field(default_factory=list)
    mask_path: Optional[Path] = None
    rendered_prompt: str
    variant: int = 1
    output_plan: Optional[OutputPlan] = None
    input_image: Optional[InputImage] = None
    status: str = "queued"


class ScanResult(CoreModel):
    images: list[InputImage] = Field(default_factory=list)
    issues: list[PreflightIssue] = Field(default_factory=list)


class JobLayout(CoreModel):
    job_id: str
    root: Path
    final_dir: Path
    partials_dir: Path
    logs_dir: Path
    app_log_path: Path
    events_jsonl_path: Path
    errors_jsonl_path: Path
    failed_dir: Path
    thumbnails_dir: Path
    manifest_path: Path
    summary_path: Path
    config_snapshot_path: Path
    command_path: Path


class PlannedJob(CoreModel):
    job: JobLayout
    tasks: list[TaskPlan] = Field(default_factory=list)
    issues: list[PreflightIssue] = Field(default_factory=list)


__all__ = [
    "InputImage",
    "JobLayout",
    "OutputPlan",
    "PlannedJob",
    "PreflightIssue",
    "ScanResult",
    "TaskPlan",
]
