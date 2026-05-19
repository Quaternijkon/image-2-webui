import json
from datetime import datetime, timezone
from typing import Any

from app.core.manifest_store import sanitize_record


ALLOWED_EVENTS = {
    "job_started",
    "task_started",
    "partial_saved",
    "task_succeeded",
    "task_failed",
    "task_canceled",
    "task_paused",
    "task_stopped",
    "job_completed",
}

REQUIRED_FIELDS = {
    "job_started": {"job_id", "total_tasks"},
    "task_started": {"job_id", "task_id"},
    "partial_saved": {"task_id", "partial_index", "path"},
    "task_succeeded": {"job_id", "task_id", "output_files"},
    "task_failed": {"task_id", "error_code", "message", "attempt"},
    "task_canceled": {"job_id", "task_id"},
    "task_paused": {"job_id", "task_id"},
    "task_stopped": {"job_id", "task_id"},
    "job_completed": {"succeeded", "failed", "skipped"},
}


class EventProtocolError(ValueError):
    pass


class EventProtocol:
    @staticmethod
    def serialize(
        event: str,
        *,
        job_id: str | None = None,
        task_id: str | None = None,
        timestamp: datetime | None = None,
        **fields: Any,
    ) -> str:
        _validate_event_name(event)
        emitted_at = timestamp or datetime.now(timezone.utc)
        record: dict[str, Any] = {
            "timestamp": emitted_at.isoformat().replace("+00:00", "Z"),
            "event": event,
        }
        if job_id is not None:
            record["job_id"] = job_id
        if task_id is not None:
            record["task_id"] = task_id
        record.update(fields)
        _validate_required_fields(event, record)
        return json.dumps(sanitize_record(record), sort_keys=True, default=str) + "\n"

    @staticmethod
    def parse_line(line: str) -> dict[str, Any]:
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EventProtocolError(f"invalid JSON event line: {exc}") from exc

        if not isinstance(record, dict):
            raise EventProtocolError("event record must be a JSON object")
        if "event" not in record:
            raise EventProtocolError("missing event field")
        _validate_event_name(str(record["event"]))
        _validate_required_fields(str(record["event"]), record)
        return sanitize_record(record)


def _validate_event_name(event: str) -> None:
    if event not in ALLOWED_EVENTS:
        raise EventProtocolError(f"unknown event: {event}")


def _validate_required_fields(event: str, record: dict[str, Any]) -> None:
    for field in sorted(REQUIRED_FIELDS[event]):
        if field not in record:
            raise EventProtocolError(f"missing required field: {field}")


__all__ = ["EventProtocol", "EventProtocolError"]
