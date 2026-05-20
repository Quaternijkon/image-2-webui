from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.core.api_capabilities import (
    get_model_capabilities,
    mode_to_image_api_endpoint,
    mode_to_responses_action,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiConfig(StrictModel):
    provider: Literal["openai"] = "openai"
    api_type: Literal["image", "responses"] = "image"
    model: Literal["gpt-image-2"] = "gpt-image-2"
    responses_model: str = "gpt-5.5"
    base_url: Optional[str] = None
    proxy_url: Optional[str] = None
    api_key_source: str = "env"
    api_key: Optional[str] = Field(default=None, exclude=True, repr=False)
    user: Optional[str] = None
    previous_response_id: Optional[str] = None
    image_generation_call_id: Optional[str] = None

    @field_validator("base_url")
    @classmethod
    def base_url_must_be_http_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip().rstrip("/")
        if not stripped:
            return None
        if not (stripped.startswith("https://") or stripped.startswith("http://")):
            raise ValueError("base_url must start with http:// or https://")
        return stripped

    @field_validator("proxy_url")
    @classmethod
    def proxy_url_must_be_http_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip().rstrip("/")
        if not stripped:
            return None
        if not (stripped.startswith("https://") or stripped.startswith("http://")):
            raise ValueError("proxy_url must start with http:// or https://")
        return stripped

    @field_validator("api_key_source")
    @classmethod
    def api_key_source_must_be_safe_reference(cls, value: str) -> str:
        if value.startswith("sk-"):
            raise ValueError("api_key_source must reference a safe key source, not secret material")

        allowed_exact = {"env", "keyring", "windows_credential_manager", "none"}
        if value in allowed_exact:
            return value

        if value.startswith("env:") and len(value) > 4:
            env_name = value[4:]
            if env_name.replace("_", "").isalnum() and not env_name[0].isdigit():
                return value

        raise ValueError("api_key_source must reference a safe key source")


class InputConfig(StrictModel):
    mode: Literal["generate", "edit", "inpaint", "mask"] = "edit"
    input_dir: Optional[Path] = None
    recursive: bool = False
    extensions: list[str] = Field(default_factory=lambda: [".png", ".jpg", ".jpeg", ".webp"])
    mask_dir: Optional[Path] = None
    reference_grouping: Literal["one_task_per_image"] = "one_task_per_image"


class PromptConfig(StrictModel):
    template: str = "Describe the image to generate or edit."
    variables_enabled: bool = True
    csv_prompt_map: Optional[Path] = None

    @field_validator("template")
    @classmethod
    def template_must_not_be_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("prompt template must not be empty")
        return value


class ImageConfig(StrictModel):
    size: str = "auto"
    quality: str = "auto"
    output_format: str = "png"
    output_compression: Optional[int] = None
    background: str = "auto"
    moderation: Literal["auto", "low"] = "auto"
    n: int = Field(default=1, ge=1, le=10)
    stream: bool = False
    partial_images: int = 0
    save_partials: bool = False

    @field_validator("size")
    @classmethod
    def size_must_be_auto_or_wxh(cls, value: str) -> str:
        if value == "auto":
            return value

        if "x" not in value:
            raise ValueError("size must be 'auto' or a WxH string such as 1024x1024")

        try:
            width_text, height_text = value.lower().split("x", 1)
            width = int(width_text)
            height = int(height_text)
        except ValueError as exc:
            raise ValueError("size must be 'auto' or a WxH string such as 1024x1024") from exc

        if width <= 0 or height <= 0:
            raise ValueError("size edges must be positive")

        return f"{width}x{height}"

    @field_validator("partial_images")
    @classmethod
    def partial_images_must_match_capabilities(cls, value: int) -> int:
        if value < 0 or value > 3:
            raise ValueError("partial_images must be between 0 and 3")
        return value

    @model_validator(mode="after")
    def compression_must_be_valid(self) -> "ImageConfig":
        if self.output_compression is not None:
            if self.output_compression < 0 or self.output_compression > 100:
                raise ValueError("output_compression must be 0-100")

        return self


class ExecutionConfig(StrictModel):
    concurrency: int = Field(default=2, ge=1, le=8)
    max_retries: int = Field(default=2, ge=0, le=5)
    timeout_seconds: int = Field(default=240, ge=30, le=600)
    failure_policy: Literal["continue", "stop"] = "continue"
    overwrite_policy: Literal["skip_existing", "overwrite", "append_counter", "new_job_dir"] = (
        "skip_existing"
    )


class OutputConfig(StrictModel):
    output_dir: Optional[Path] = None
    job_subdir_enabled: bool = True
    filename_template: str = "{stem}_gpt_{variant}.{ext}"
    save_manifest: bool = True
    save_logs: bool = True
    save_config_snapshot: bool = True


class AppConfig(StrictModel):
    version: int = 1
    api: ApiConfig = Field(default_factory=ApiConfig)
    input: InputConfig = Field(default_factory=InputConfig)
    prompt: PromptConfig = Field(default_factory=PromptConfig)
    image: ImageConfig = Field(default_factory=ImageConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @model_validator(mode="after")
    def options_must_match_api_capabilities(self) -> "AppConfig":
        capabilities = get_model_capabilities(self.api.model)
        image = self.image

        if self.api.api_type == "image":
            endpoint = mode_to_image_api_endpoint(self.input.mode)
            if not capabilities["image_api"].get(endpoint, False):
                verb = "edit" if endpoint == "edits" else endpoint.rstrip("s")
                raise ValueError(f"{self.api.model} does not support {verb} with Image API")
        else:
            if not capabilities.get("responses_api", False):
                raise ValueError(f"{self.api.model} does not support Responses API image generation")
            mode_to_responses_action(self.input.mode)

        prompt_limit = int(capabilities.get("prompt_max_chars", 0) or 0)
        if prompt_limit and len(self.prompt.template) > prompt_limit:
            raise ValueError(f"prompt template must be <= {prompt_limit} characters for {self.api.model}")

        max_n = int(capabilities.get("max_n", 10))
        if image.n > max_n:
            raise ValueError(f"{self.api.model} supports n=1 only" if max_n == 1 else f"n must be <= {max_n}")

        self._validate_size(capabilities)
        self._validate_quality(capabilities)
        self._validate_output_format(capabilities)
        self._validate_background(capabilities)
        self._validate_moderation(capabilities)
        self._validate_streaming(capabilities)
        self._validate_compression(capabilities)

        return self

    def _validate_size(self, capabilities: dict[str, object]) -> None:
        size_config = capabilities["size"]
        assert isinstance(size_config, dict)
        value = self.image.size
        if value == "auto":
            if size_config.get("auto", False):
                return
            raise ValueError(f"size=auto is not supported for {self.api.model}")

        allowed = size_config.get("allowed") or []
        if value in allowed:
            return

        if "edge_multiple" not in size_config:
            allowed_text = ", ".join(str(item) for item in allowed)
            raise ValueError(f"size must be one of {allowed_text} for {self.api.model}")

        width, height = _parse_size(value)
        max_edge = int(size_config["max_edge"])
        if width > max_edge or height > max_edge:
            raise ValueError(f"each size edge must be <= {max_edge}")

        multiple = int(size_config["edge_multiple"])
        if width % multiple != 0 or height % multiple != 0:
            raise ValueError(f"each size edge must be a multiple of {multiple}")

        long_edge = max(width, height)
        short_edge = min(width, height)
        if long_edge / short_edge > float(size_config["max_long_short_ratio"]):
            raise ValueError("long:short size ratio must be <= 3:1")

        pixels = width * height
        min_pixels = int(size_config["min_pixels"])
        max_pixels = int(size_config["max_pixels"])
        if pixels < min_pixels or pixels > max_pixels:
            raise ValueError(f"total pixels must be between {min_pixels} and {max_pixels}")

    def _validate_quality(self, capabilities: dict[str, object]) -> None:
        qualities = list(capabilities.get("qualities", []))
        if self.image.quality == "auto" and "auto" not in qualities:
            return
        if self.image.quality not in qualities:
            raise ValueError("quality must be one of " + ", ".join(qualities))

    def _validate_output_format(self, capabilities: dict[str, object]) -> None:
        output_formats = list(capabilities.get("output_formats", []))
        if output_formats:
            if self.image.output_format not in output_formats:
                raise ValueError("output_format must be one of " + ", ".join(output_formats))
            return
        if self.image.output_format != "png":
            raise ValueError(f"output_format is not supported for {self.api.model}; use png output files")

    def _validate_background(self, capabilities: dict[str, object]) -> None:
        backgrounds = list(capabilities.get("backgrounds", []))
        if self.image.background == "auto" and not backgrounds:
            return
        if self.image.background not in backgrounds:
            raise ValueError(f"background is not supported for {self.api.model}")
        if self.image.background == "transparent" and not capabilities.get("transparent_background", False):
            raise ValueError(f"transparent background is not supported for {self.api.model}")
        if self.image.background == "transparent" and self.image.output_format == "jpeg":
            raise ValueError("transparent background requires png or webp output_format")

    def _validate_moderation(self, capabilities: dict[str, object]) -> None:
        moderations = list(capabilities.get("moderations", []))
        if self.image.moderation == "auto" and not moderations:
            return
        if self.image.moderation not in moderations:
            raise ValueError(f"moderation is not supported for {self.api.model}")

    def _validate_streaming(self, capabilities: dict[str, object]) -> None:
        supports_stream = bool(capabilities.get("stream", False))
        partial_bounds = capabilities.get("partial_images", {"minimum": 0, "maximum": 0})
        assert isinstance(partial_bounds, dict)
        if self.image.stream and not supports_stream:
            raise ValueError(f"stream is not supported for {self.api.model}")
        if self.image.partial_images:
            if not self.image.stream:
                raise ValueError("partial_images requires stream=true")
            if not supports_stream:
                raise ValueError(f"partial_images is not supported for {self.api.model}")
        if self.image.partial_images < int(partial_bounds["minimum"]) or self.image.partial_images > int(
            partial_bounds["maximum"]
        ):
            raise ValueError(
                f"partial_images must be between {partial_bounds['minimum']} and {partial_bounds['maximum']}"
            )

    def _validate_compression(self, capabilities: dict[str, object]) -> None:
        if self.image.output_compression is None:
            return
        compression_formats = list(capabilities.get("compression_formats", []))
        if self.image.output_format not in compression_formats:
            raise ValueError("output_compression only applies to jpeg/webp output")


def _parse_size(value: str) -> tuple[int, int]:
    width_text, height_text = value.lower().split("x", 1)
    return int(width_text), int(height_text)


__all__ = [
    "ApiConfig",
    "AppConfig",
    "ExecutionConfig",
    "ImageConfig",
    "InputConfig",
    "OutputConfig",
    "PromptConfig",
    "ValidationError",
]
