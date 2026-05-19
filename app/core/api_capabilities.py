import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CAPABILITIES_PATH = Path(__file__).resolve().parents[1] / "api_capabilities.json"


@lru_cache(maxsize=1)
def load_api_capabilities() -> dict[str, Any]:
    with CAPABILITIES_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def get_model_capabilities(model: str) -> dict[str, Any]:
    capabilities = load_api_capabilities()
    try:
        return capabilities["models"][model]
    except KeyError as exc:
        raise ValueError(f"Unsupported image model: {model}") from exc


def mode_to_image_api_endpoint(mode: str) -> str:
    if mode == "generate":
        return "generations"
    if mode in {"edit", "inpaint", "mask"}:
        return "edits"
    raise ValueError(f"Unsupported input mode: {mode}")


def mode_to_responses_action(mode: str) -> str:
    if mode == "generate":
        return "generate"
    if mode in {"edit", "inpaint", "mask"}:
        return "edit"
    raise ValueError(f"Unsupported Responses image generation mode: {mode}")
