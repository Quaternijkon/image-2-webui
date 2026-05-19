from __future__ import annotations

import base64
import binascii
import errno
import os
from pathlib import Path
from uuid import uuid4

from app.core.errors import ImageBatchError
from app.core.models import TaskPlan


TEMPORARY_WRITE_ERRNOS = {
    errno.EAGAIN,
    errno.EBUSY,
    errno.ENFILE,
    errno.EMFILE,
}

TEMPORARY_WRITE_WINERRORS = {
    32,  # ERROR_SHARING_VIOLATION: another process has the file open.
    33,  # ERROR_LOCK_VIOLATION: a byte range is locked.
}


class OutputWriter:
    def __init__(self, *, output_root: Path | None = None) -> None:
        self.output_root = output_root

    def write_final(self, task: TaskPlan, b64_json: str) -> Path:
        if task.output_plan is None:
            raise ImageBatchError("write_error", "task has no output plan")
        return self._write_b64(task.output_plan.final_path, b64_json)

    def write_partial(
        self,
        task: TaskPlan,
        b64_json: str,
        *,
        partial_index: int,
        output_format: str,
    ) -> Path:
        if task.output_plan is None:
            raise ImageBatchError("write_error", "task has no output plan")
        extension = output_format.lower().lstrip(".")
        partial_path = task.output_plan.partials_dir / f"partial_{partial_index}.{extension}"
        return self._write_b64(partial_path, b64_json)

    def _write_b64(self, path: Path, b64_json: str) -> Path:
        self._validate_output_path(path)
        try:
            payload = base64.b64decode(b64_json, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ImageBatchError("decode_error", "image payload is not valid base64") from exc
        return self._write_bytes(path, payload)

    def _write_bytes(self, path: Path, payload: bytes) -> Path:
        tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tmp_path.open("wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            tmp_path.replace(path)
            return path
        except OSError as exc:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise ImageBatchError(
                "write_error",
                str(exc),
                retryable=_is_temporary_write_error(exc),
            ) from exc

    def _validate_output_path(self, path: Path) -> None:
        if ".." in path.parts:
            raise ImageBatchError("write_error", f"unsafe output path: {path}", retryable=False)
        if self.output_root is None:
            return
        try:
            path.resolve(strict=False).relative_to(self.output_root.resolve(strict=False))
        except ValueError as exc:
            raise ImageBatchError(
                "write_error",
                f"output path is outside job root: {path}",
                retryable=False,
            ) from exc


def _is_temporary_write_error(exc: OSError) -> bool:
    if getattr(exc, "winerror", None) in TEMPORARY_WRITE_WINERRORS:
        return True
    return exc.errno in TEMPORARY_WRITE_ERRNOS


__all__ = ["OutputWriter"]
