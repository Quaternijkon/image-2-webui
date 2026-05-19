from __future__ import annotations

import json
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def list_history(output_root: Path | str) -> list[dict[str, str]]:
    root = Path(output_root)
    if not root.exists():
        return []

    job_roots = [
        candidate
        for candidate in root.iterdir()
        if candidate.is_dir() and (candidate / "summary.json").exists()
    ]
    job_roots.sort(key=lambda path: path.name)
    job_roots.sort(key=lambda path: (path / "summary.json").stat().st_mtime_ns, reverse=True)
    return [_history_row(job_root) for job_root in job_roots]


def job_gallery_paths(job_root: Path | str) -> list[Path]:
    final_dir = Path(job_root) / "final"
    if not final_dir.exists():
        return []
    return sorted(
        path
        for path in final_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def _history_row(job_root: Path) -> dict[str, str]:
    summary = _read_json(job_root / "summary.json")
    return {
        "job_id": job_root.name,
        "total": str(summary.get("total", "")),
        "succeeded": str(summary.get("succeeded", "")),
        "failed": str(summary.get("failed", "")),
        "skipped": str(summary.get("skipped", "")),
        "path": str(job_root),
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


__all__ = ["IMAGE_EXTENSIONS", "job_gallery_paths", "list_history"]
