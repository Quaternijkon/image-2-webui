from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from app.core.api_capabilities import get_model_capabilities


MODEL = "gpt-image-2"


@dataclass(frozen=True)
class AspectPreset:
    label: str
    ratio: float | None


@dataclass(frozen=True)
class PixelBudgetPreset:
    label: str
    pixels: int | None


@dataclass(frozen=True)
class ComputedSize:
    width: int
    height: int
    total_pixels: int
    aspect_ratio: float
    size: str
    validation_message: str | None = None


ASPECT_PRESETS: dict[str, AspectPreset] = {
    "square": AspectPreset("方图 1:1", 1.0),
    "landscape": AspectPreset("横图 3:2", 3 / 2),
    "portrait": AspectPreset("竖图 2:3", 2 / 3),
    "widescreen": AspectPreset("宽屏 16:9", 16 / 9),
    "vertical": AspectPreset("竖屏 9:16", 9 / 16),
    "product_landscape": AspectPreset("产品横图 4:3", 4 / 3),
    "product_portrait": AspectPreset("产品竖图 3:4", 3 / 4),
    "ultra_wide_safe": AspectPreset("超宽安全比例 3:1", 3.0),
    "custom": AspectPreset("自定义", None),
}

PIXEL_BUDGET_PRESETS: dict[str, PixelBudgetPreset] = {
    "low": PixelBudgetPreset("低", 655_360),
    "standard": PixelBudgetPreset("标准", 1_048_576),
    "large": PixelBudgetPreset("大", 2_359_296),
    "max": PixelBudgetPreset("最大", 8_294_400),
    "custom": PixelBudgetPreset("自定义", None),
}


def compute_size_from_presets(aspect_key: str, pixel_budget_key: str) -> ComputedSize:
    aspect = ASPECT_PRESETS[aspect_key]
    if aspect.ratio is None:
        return validate_custom_size(1024, 1024)

    pixel_budget = PIXEL_BUDGET_PRESETS[pixel_budget_key]
    target_pixels = pixel_budget.pixels or _size_capabilities()["min_pixels"]
    target_pixels = _clamp(
        target_pixels,
        int(_size_capabilities()["min_pixels"]),
        int(_size_capabilities()["max_pixels"]),
    )
    width = sqrt(target_pixels * aspect.ratio)
    height = width / aspect.ratio
    return _nearest_valid_size(int(round(width)), int(round(height)), aspect.ratio)


def validate_custom_size(width: int, height: int) -> ComputedSize:
    return _computed_size(width, height, validation_message=_validation_message(width, height))


def _nearest_valid_size(width: int, height: int, target_ratio: float) -> ComputedSize:
    caps = _size_capabilities()
    multiple = int(caps["edge_multiple"])
    min_pixels = int(caps["min_pixels"])
    max_pixels = int(caps["max_pixels"])
    max_edge = int(caps["max_edge"])

    best: ComputedSize | None = None
    best_score: float | None = None
    base_width = _round_to_multiple(width, multiple)
    base_height = _round_to_multiple(height, multiple)
    search_radius = max(multiple * 32, 512)
    for candidate_width in range(max(multiple, base_width - search_radius), min(max_edge, base_width + search_radius) + 1, multiple):
        for candidate_height in range(max(multiple, base_height - search_radius), min(max_edge, base_height + search_radius) + 1, multiple):
            pixels = candidate_width * candidate_height
            if pixels < min_pixels or pixels > max_pixels:
                continue
            message = _validation_message(candidate_width, candidate_height)
            if message:
                continue
            ratio = candidate_width / candidate_height
            score = abs(ratio - target_ratio) + abs(pixels - width * height) / max_pixels
            if best_score is None or score < best_score:
                best_score = score
                best = _computed_size(candidate_width, candidate_height)

    if best is not None:
        return best
    return _computed_size(base_width, base_height, validation_message=_validation_message(base_width, base_height))


def _computed_size(width: int, height: int, *, validation_message: str | None = None) -> ComputedSize:
    safe_height = height if height else 1
    return ComputedSize(
        width=width,
        height=height,
        total_pixels=width * height,
        aspect_ratio=width / safe_height,
        size=f"{width}x{height}",
        validation_message=validation_message,
    )


def _validation_message(width: int, height: int) -> str | None:
    caps = _size_capabilities()
    if width <= 0 or height <= 0:
        return "宽度和高度必须为正数"
    multiple = int(caps["edge_multiple"])
    if width % multiple != 0 or height % multiple != 0:
        return f"宽度和高度必须是 {multiple} 的倍数"
    max_edge = int(caps["max_edge"])
    if width > max_edge or height > max_edge:
        return f"每条边必须小于等于 {max_edge}"
    ratio = max(width, height) / min(width, height)
    max_ratio = float(caps["max_long_short_ratio"])
    if ratio > max_ratio:
        return f"长边与短边比例必须小于等于 {max_ratio:g}:1"
    pixels = width * height
    min_pixels = int(caps["min_pixels"])
    if pixels < min_pixels:
        return f"总像素必须大于等于 {min_pixels}"
    max_pixels = int(caps["max_pixels"])
    if pixels > max_pixels:
        return f"总像素必须小于等于 {max_pixels}"
    return None


def _round_to_multiple(value: int, multiple: int) -> int:
    rounded = round(value / multiple) * multiple
    return max(multiple, int(rounded))


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _size_capabilities() -> dict[str, object]:
    capabilities = get_model_capabilities(MODEL)
    size = capabilities["size"]
    assert isinstance(size, dict)
    return size


__all__ = [
    "ASPECT_PRESETS",
    "PIXEL_BUDGET_PRESETS",
    "AspectPreset",
    "ComputedSize",
    "PixelBudgetPreset",
    "compute_size_from_presets",
    "validate_custom_size",
]
