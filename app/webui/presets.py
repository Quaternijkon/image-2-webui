from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from app.webui.state import WebFormState


@dataclass(frozen=True)
class ScenarioPreset:
    label: str
    description: str
    values: dict[str, Any]


SCENARIO_PRESETS: dict[str, ScenarioPreset] = {
    "fastest_draft": ScenarioPreset(
        label="最快草稿",
        description="低质量、低像素预算，不返回局部预览。",
        values={
            "mode": "generate",
            "size_mode": "preset",
            "aspect_preset": "square",
            "pixel_budget_preset": "low",
            "quality": "low",
            "image_count": 1,
            "stream": False,
            "partial_images": 0,
            "save_partials": False,
        },
    ),
    "balanced_preview": ScenarioPreset(
        label="均衡预览",
        description="中等质量的标准方图预览。",
        values={
            "mode": "generate",
            "size_mode": "preset",
            "aspect_preset": "square",
            "pixel_budget_preset": "standard",
            "quality": "medium",
            "image_count": 1,
        },
    ),
    "standard_square": ScenarioPreset(
        label="标准方图/社媒",
        description="适合社媒和通用输出的标准方图。",
        values={
            "mode": "generate",
            "size_mode": "preset",
            "aspect_preset": "square",
            "pixel_budget_preset": "standard",
            "quality": "auto",
        },
    ),
    "widescreen": ScenarioPreset(
        label="宽屏",
        description="16:9 横向构图。",
        values={
            "mode": "generate",
            "size_mode": "preset",
            "aspect_preset": "widescreen",
            "pixel_budget_preset": "standard",
            "quality": "auto",
        },
    ),
    "vertical_social": ScenarioPreset(
        label="竖版社媒",
        description="9:16 竖向构图。",
        values={
            "mode": "generate",
            "size_mode": "preset",
            "aspect_preset": "vertical",
            "pixel_budget_preset": "standard",
            "quality": "auto",
        },
    ),
    "product_image": ScenarioPreset(
        label="产品图",
        description="适合产品展示的 4:3 构图，并使用不透明背景。",
        values={
            "mode": "generate",
            "size_mode": "preset",
            "aspect_preset": "product_landscape",
            "pixel_budget_preset": "standard",
            "quality": "medium",
            "background": "opaque",
        },
    ),
    "high_quality": ScenarioPreset(
        label="高质量",
        description="更高质量和更大的像素预算。",
        values={
            "mode": "generate",
            "size_mode": "preset",
            "aspect_preset": "square",
            "pixel_budget_preset": "large",
            "quality": "high",
        },
    ),
    "asset_workflow": ScenarioPreset(
        label="素材工作流",
        description="输出 WebP 素材，并为 gpt-image-2 使用不透明背景。",
        values={
            "mode": "generate",
            "size_mode": "preset",
            "aspect_preset": "square",
            "pixel_budget_preset": "standard",
            "quality": "medium",
            "output_format": "webp",
            "output_compression": 80,
            "background": "opaque",
        },
    ),
    "batch_edit": ScenarioPreset(
        label="批量编辑",
        description="编辑模式，每个输入生成一张图，并使用保守并发。",
        values={
            "mode": "edit",
            "size_mode": "auto",
            "image_count": 1,
            "concurrency": 2,
            "stream": False,
            "partial_images": 0,
            "save_partials": False,
        },
    ),
}


def apply_scenario_preset(state: WebFormState, preset_key: str) -> WebFormState:
    preset = SCENARIO_PRESETS[preset_key]
    return replace(state, **preset.values)


__all__ = ["SCENARIO_PRESETS", "ScenarioPreset", "apply_scenario_preset"]
