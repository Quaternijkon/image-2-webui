from math import ceil
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.core.config import AppConfig
from app.core.models import PlannedJob


_QUALITY_MULTIPLIERS = {
    "low": 1.0,
    "medium": 2.0,
    "high": 4.0,
    "auto": 2.0,
}
_LOW_QUALITY_1024_SQUARE_OUTPUT_TOKENS = 196
_PARTIAL_IMAGE_OUTPUT_TOKENS = 100


class CostEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    estimated: bool
    task_count: int
    estimated_output_images: int
    estimated_partial_images: int
    estimated_prompt_tokens: int
    estimated_input_image_tokens: int
    estimated_output_image_tokens: int
    estimated_partial_image_tokens: int
    estimated_total_tokens: int
    estimated_image_token_units: int
    estimated_total_token_units: int
    cost_usd: Optional[float]
    note: str


class CostEstimator:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def estimate(self, planned: PlannedJob) -> CostEstimate:
        task_count = len(planned.tasks)
        prompt_tokens = sum(_estimate_text_tokens(task.rendered_prompt) for task in planned.tasks)
        output_images = task_count
        partial_images = task_count * self.config.image.partial_images
        input_image_tokens = sum(_estimate_input_image_tokens(len(task.source_paths)) for task in planned.tasks)
        output_image_tokens = output_images * _estimate_output_image_tokens(
            self.config.image.size,
            self.config.image.quality,
        )
        partial_image_tokens = partial_images * _PARTIAL_IMAGE_OUTPUT_TOKENS
        total_tokens = prompt_tokens + input_image_tokens + output_image_tokens + partial_image_tokens

        return CostEstimate(
            estimated=True,
            task_count=task_count,
            estimated_output_images=output_images,
            estimated_partial_images=partial_images,
            estimated_prompt_tokens=prompt_tokens,
            estimated_input_image_tokens=input_image_tokens,
            estimated_output_image_tokens=output_image_tokens,
            estimated_partial_image_tokens=partial_image_tokens,
            estimated_total_tokens=total_tokens,
            estimated_image_token_units=output_image_tokens,
            estimated_total_token_units=total_tokens,
            cost_usd=None,
            note="这里只提供 token 预估；实际用量以 API 返回为准，且不包含美元价格。",
        )


def _estimate_text_tokens(text: str) -> int:
    return max(1, ceil(len(text) / 4))


def _estimate_input_image_tokens(image_count: int) -> int:
    return image_count * _LOW_QUALITY_1024_SQUARE_OUTPUT_TOKENS


def _estimate_output_image_tokens(size: str, quality: str) -> int:
    width, height = _parse_size_or_default(size)
    pixels = width * height
    base = _LOW_QUALITY_1024_SQUARE_OUTPUT_TOKENS * (pixels / (1024 * 1024))
    multiplier = _QUALITY_MULTIPLIERS.get(quality, _QUALITY_MULTIPLIERS["auto"])
    return max(1, ceil(base * multiplier))


def _parse_size_or_default(size: str) -> tuple[int, int]:
    if size == "auto":
        return 1024, 1024
    try:
        width_text, height_text = size.lower().split("x", 1)
        return int(width_text), int(height_text)
    except ValueError:
        return 1024, 1024


__all__ = ["CostEstimate", "CostEstimator"]
