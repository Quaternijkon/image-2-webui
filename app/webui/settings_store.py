from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.webui.state import WebFormState


def default_settings_path() -> Path:
    return Path.home() / ".gpt-image-batch" / "webui-settings.json"


def save_settings(path: Path, state: WebFormState) -> Path:
    payload = state.to_safe_payload()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def load_settings(path: Path) -> WebFormState:
    if not path.exists():
        return WebFormState()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return WebFormState()
    payload.pop("api_key", None)
    return WebFormState(**_restore_paths(payload))


def _restore_paths(payload: dict[str, Any]) -> dict[str, Any]:
    restored = dict(payload)
    for key in ["input_dir", "output_dir"]:
        value = restored.get(key)
        if value:
            restored[key] = Path(value)
    return restored


__all__ = ["default_settings_path", "load_settings", "save_settings"]
