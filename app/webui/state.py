from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from app.core.api_capabilities import get_model_capabilities
from app.core.config import AppConfig
from app.core.manifest_store import sanitize_record
from app.webui.sizing import compute_size_from_presets, validate_custom_size


@dataclass(frozen=True)
class WebFormState:
    input_dir: Path | None = None
    output_dir: Path | None = None
    prompt: str = "描述你想生成或编辑的图片。"
    mode: Literal["generate", "edit", "inpaint", "mask"] = "generate"
    api_type: Literal["image", "responses"] = "image"
    responses_model: str = "gpt-5.5"
    base_url: str | None = None
    api_key_source: str = "env"
    api_key: str | None = None
    user: str | None = None
    previous_response_id: str | None = None
    image_generation_call_id: str | None = None
    size_mode: Literal["auto", "preset", "custom"] = "preset"
    aspect_preset: str = "square"
    pixel_budget_preset: str = "standard"
    width: int = 1024
    height: int = 1024
    quality: str = "auto"
    output_format: str = "png"
    output_compression: int | None = None
    background: str = "auto"
    moderation: str = "auto"
    stream: bool = False
    partial_images: int = 0
    save_partials: bool = False
    image_count: int = 1
    concurrency: int = 2
    max_retries: int = 2
    timeout_seconds: int = 240
    failure_policy: Literal["continue", "stop"] = "continue"
    overwrite_policy: Literal["skip_existing", "overwrite", "append_counter", "new_job_dir"] = "skip_existing"

    def build_config(self) -> AppConfig:
        api_payload: dict[str, Any] = {
            "api_type": self.api_type,
            "model": "gpt-image-2",
            "responses_model": self.responses_model,
            "api_key_source": self.api_key_source,
        }
        for key, value in [
            ("base_url", self.base_url),
            ("api_key", self.api_key),
            ("user", self.user),
            ("previous_response_id", self.previous_response_id),
            ("image_generation_call_id", self.image_generation_call_id),
        ]:
            if value:
                api_payload[key] = value

        image_payload: dict[str, Any] = {
            "size": self._resolved_size(),
            "quality": self.quality,
            "output_format": self.output_format,
            "background": self.background,
            "moderation": self.moderation,
            "n": self.image_count,
            "stream": self.stream,
            "partial_images": self.partial_images,
            "save_partials": self.save_partials,
        }
        if self.output_compression is not None and self.output_format != "png":
            image_payload["output_compression"] = self.output_compression

        return AppConfig(
            api=api_payload,
            input={
                "mode": self.mode,
                **({"input_dir": self.input_dir} if self.input_dir else {}),
            },
            prompt={"template": self.prompt},
            image=image_payload,
            execution={
                "concurrency": self.concurrency,
                "max_retries": self.max_retries,
                "timeout_seconds": self.timeout_seconds,
                "failure_policy": self.failure_policy,
                "overwrite_policy": self.overwrite_policy,
            },
            output={
                **({"output_dir": self.output_dir} if self.output_dir else {}),
                "job_subdir_enabled": False,
            },
        )

    def to_safe_payload(self) -> dict[str, Any]:
        return sanitize_record(_json_safe(asdict(self)))

    def _resolved_size(self) -> str:
        if self.size_mode == "auto":
            return "auto"
        if self.size_mode == "preset":
            return compute_size_from_presets(self.aspect_preset, self.pixel_budget_preset).size
        return validate_custom_size(self.width, self.height).size


def available_option_sets() -> dict[str, list[Any]]:
    capabilities = get_model_capabilities("gpt-image-2")
    partial_bounds = capabilities.get("partial_images", {"minimum": 0, "maximum": 0})
    assert isinstance(partial_bounds, dict)
    return {
        "api_type": ["image", "responses"],
        "mode": ["generate", "edit", "inpaint", "mask"],
        "quality": list(capabilities.get("qualities", [])),
        "output_format": list(capabilities.get("output_formats", [])),
        "background": list(capabilities.get("backgrounds", [])),
        "moderation": list(capabilities.get("moderations", [])),
        "partial_images": list(range(int(partial_bounds["minimum"]), int(partial_bounds["maximum"]) + 1)),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


__all__ = ["WebFormState", "available_option_sets"]
