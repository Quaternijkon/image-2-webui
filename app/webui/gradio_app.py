from __future__ import annotations

from dataclasses import dataclass
import base64
from io import BytesIO
import json
from pathlib import Path
from typing import Any

from app.core.cost_estimator import CostEstimate
from app.webui.history import job_gallery_paths, list_history
from app.webui.job_runner import WebJobRunner, WebJobSnapshot, snapshot_to_log_text
from app.webui.presets import SCENARIO_PRESETS
from app.webui.settings_store import default_settings_path, load_settings, save_settings
from app.webui.sizing import (
    ASPECT_PRESETS,
    PIXEL_BUDGET_PRESETS,
    compute_size_from_presets,
    validate_custom_size,
)
from app.webui.state import WebFormState, available_option_sets


INPUT_NAMES = [
    "mode",
    "api_type",
    "responses_model",
    "base_url",
    "proxy_url",
    "api_key_source",
    "api_key",
    "user",
    "previous_response_id",
    "image_generation_call_id",
    "prompt",
    "input_dir",
    "output_dir",
    "size_mode",
    "aspect_preset",
    "pixel_budget_preset",
    "width",
    "height",
    "quality",
    "output_format",
    "output_compression_enabled",
    "output_compression",
    "background",
    "moderation",
    "stream",
    "partial_images",
    "save_partials",
    "image_count",
    "concurrency",
    "max_retries",
    "timeout_seconds",
    "failure_policy",
    "overwrite_policy",
]


MODE_LABELS = {
    "generate": "生成",
    "edit": "编辑",
    "inpaint": "局部重绘",
    "mask": "蒙版编辑",
}
API_TYPE_LABELS = {
    "image": "Images API（单轮生成/编辑）",
    "responses": "Responses API（多轮上下文）",
}
SIZE_MODE_LABELS = {
    "auto": "自动",
    "preset": "预设",
    "custom": "自定义",
}
QUALITY_LABELS = {
    "auto": "自动",
    "low": "低",
    "medium": "中",
    "high": "高",
}
OUTPUT_FORMAT_LABELS = {
    "png": "PNG",
    "jpeg": "JPEG",
    "webp": "WebP",
}
BACKGROUND_LABELS = {
    "auto": "自动",
    "opaque": "不透明",
}
MODERATION_LABELS = {
    "auto": "自动",
    "low": "低干预",
}
FAILURE_POLICY_LABELS = {
    "continue": "失败后继续",
    "stop": "失败后停止",
}
OVERWRITE_POLICY_LABELS = {
    "skip_existing": "跳过已有文件",
    "overwrite": "覆盖",
    "append_counter": "追加序号",
    "new_job_dir": "新建任务目录",
}
STATUS_LABELS = {
    "dry_run": "试运行完成",
    "running": "运行中",
    "completed": "已完成",
    "queued": "排队中",
    "validation_failed": "验证失败",
    "succeeded": "成功",
    "failed": "失败",
    "skipped": "已跳过",
    "paused": "已暂停",
    "cancelled": "已取消",
}


@dataclass(frozen=True)
class GradioOutputs:
    status: str
    estimate_markdown: str
    task_rows: list[list[str]]
    log_text: str
    gallery: list[str]
    current_preview: str | None
    usage: dict[str, object] | None
    command_preview: str


def build_state_from_ui(
    *,
    mode: str,
    api_type: str,
    responses_model: str,
    base_url: str,
    proxy_url: str,
    api_key_source: str,
    api_key: str,
    user: str,
    previous_response_id: str,
    image_generation_call_id: str,
    prompt: str,
    input_dir: str,
    output_dir: str,
    size_mode: str,
    aspect_preset: str,
    pixel_budget_preset: str,
    width: int | float,
    height: int | float,
    quality: str,
    output_format: str,
    output_compression_enabled: bool,
    output_compression: int | float,
    background: str,
    moderation: str,
    stream: bool,
    partial_images: int | float,
    save_partials: bool,
    image_count: int | float,
    concurrency: int | float,
    max_retries: int | float,
    timeout_seconds: int | float,
    failure_policy: str,
    overwrite_policy: str,
) -> WebFormState:
    compression = int(output_compression) if output_compression_enabled else None
    return WebFormState(
        input_dir=_optional_path(input_dir),
        output_dir=_optional_path(output_dir),
        prompt=prompt,
        mode=mode,  # type: ignore[arg-type]
        api_type=api_type,  # type: ignore[arg-type]
        responses_model=responses_model.strip() or "gpt-5.5",
        base_url=base_url.strip() or None,
        proxy_url=proxy_url.strip() or None,
        api_key_source=api_key_source.strip() or "env",
        api_key=api_key or None,
        user=user.strip() or None,
        previous_response_id=previous_response_id.strip() or None,
        image_generation_call_id=image_generation_call_id.strip() or None,
        size_mode=size_mode,  # type: ignore[arg-type]
        aspect_preset=aspect_preset,
        pixel_budget_preset=pixel_budget_preset,
        width=int(width),
        height=int(height),
        quality=quality,
        output_format=output_format,
        output_compression=compression,
        background=background,
        moderation=moderation,
        stream=stream,
        partial_images=int(partial_images),
        save_partials=save_partials,
        image_count=int(image_count),
        concurrency=int(concurrency),
        max_retries=int(max_retries),
        timeout_seconds=int(timeout_seconds),
        failure_policy=failure_policy,  # type: ignore[arg-type]
        overwrite_policy=overwrite_policy,  # type: ignore[arg-type]
    )


def snapshot_to_outputs(snapshot: WebJobSnapshot) -> GradioOutputs:
    return GradioOutputs(
        status=_snapshot_status_label(snapshot),
        estimate_markdown=format_estimate_markdown(snapshot.estimate),
        task_rows=[
            [row["task_id"], _status_label(row["status"]), row.get("message", "")]
            for row in snapshot.task_rows
        ],
        log_text=snapshot_to_log_text(snapshot),
        gallery=[str(path) for path in snapshot.output_files],
        current_preview=_preview_image(snapshot.current_preview_b64),
        usage=snapshot.actual_usage,
        command_preview=snapshot.command_preview,
    )


def format_estimate_markdown(estimate: CostEstimate) -> str:
    return "\n".join(
        [
            "### Token 预估",
            f"- 影响等级: `{_token_impact(estimate.estimated_total_tokens)}`",
            f"- 任务数: `{estimate.task_count}`",
            f"- 预估提示词 token: `{estimate.estimated_prompt_tokens}`",
            f"- 预估输入图片 token: `{estimate.estimated_input_image_tokens}`",
            f"- 预估输出图片 token: `{estimate.estimated_output_image_tokens}`",
            f"- 预估局部预览 token: `{estimate.estimated_partial_image_tokens}`",
            f"- 预估总 token: `{estimate.estimated_total_tokens}`",
            "",
            estimate.note,
        ]
    )


def apply_scenario_preset_to_values(preset_key: str, values: dict[str, Any]) -> dict[str, Any]:
    updated = dict(values)
    preset = SCENARIO_PRESETS[preset_key]
    updated.update(preset.values)
    if preset.values.get("output_compression") is not None:
        updated["output_compression_enabled"] = True
    return updated


def validate_size_feedback(
    size_mode: str,
    aspect_preset: str,
    pixel_budget_preset: str,
    width: int | float | None,
    height: int | float | None,
) -> tuple[str, int, int]:
    resolved_width = _coerce_int(width, 1024)
    resolved_height = _coerce_int(height, 1024)
    if size_mode == "auto":
        return "解析尺寸: `auto`", resolved_width, resolved_height

    if size_mode == "preset":
        size = compute_size_from_presets(aspect_preset, pixel_budget_preset)
        return (
            f"解析尺寸: `{size.size}` ({size.total_pixels:,} px，宽高比 {size.aspect_ratio:.3g})",
            size.width,
            size.height,
        )

    size = validate_custom_size(resolved_width, resolved_height)
    if size.validation_message:
        return f"尺寸校验: {size.validation_message}", size.width, size.height
    return (
        f"解析尺寸: `{size.size}` ({size.total_pixels:,} px，宽高比 {size.aspect_ratio:.3g})",
        size.width,
        size.height,
    )


def pause_current_job(runner: WebJobRunner) -> str:
    try:
        path = runner.request_pause()
    except RuntimeError as exc:
        return str(exc)
    return f"已请求暂停: {path}"


def cancel_current_job(runner: WebJobRunner) -> str:
    try:
        path = runner.request_cancel()
    except RuntimeError as exc:
        return str(exc)
    return f"已请求取消: {path}"


def build_demo(runner: WebJobRunner | None = None):
    try:
        import gradio as gr
    except ImportError as exc:
        raise RuntimeError("WebUI 需要 Gradio。请先安装 pyproject.toml 或 requirements.txt 中的依赖。") from exc

    runner = runner or WebJobRunner()
    options = available_option_sets()

    with gr.Blocks(title="GPT 图像批量生成 WebUI", css=_CSS) as demo:
        gr.Markdown("# GPT 图像批量生成 WebUI")
        with gr.Row():
            with gr.Column(scale=1):
                scenario_preset = gr.Dropdown(scenario_preset_choices(), value="balanced_preview", label="场景预设")
                apply_preset = gr.Button("应用预设")
                mode = gr.Dropdown(_choices(options["mode"], MODE_LABELS), value="generate", label="任务模式")
                api_type = gr.Dropdown(_choices(options["api_type"], API_TYPE_LABELS), value="image", label="API 路由")

                with gr.Accordion("API 与多轮上下文", open=False):
                    responses_model = gr.Textbox(value="gpt-5.5", label="Responses 模型")
                    base_url = gr.Textbox(label="Base URL（可选）", placeholder="http://66.225.232.37:8317")
                    proxy_url = gr.Textbox(label="代理 URL（可选）", placeholder="http://127.0.0.1:10808")
                    api_key_source = gr.Textbox(value="env", label="API Key 来源")
                    api_key = gr.Textbox(label="API Key", type="password")
                    user = gr.Textbox(label="用户标识（可选）")
                    previous_response_id = gr.Textbox(label="上一轮 response ID（Responses API）")
                    image_generation_call_id = gr.Textbox(label="图像生成调用 ID（Responses API）")

                prompt = gr.Textbox(value="生成一张清晰、干净的图片。", label="提示词", lines=5)
                input_dir = gr.Textbox(label="输入文件夹")
                output_dir = gr.Textbox(label="输出文件夹", value=str(Path.cwd() / "output-webui"))

                with gr.Accordion("图像参数", open=True):
                    size_mode = gr.Radio(_choices(["auto", "preset", "custom"], SIZE_MODE_LABELS), value="preset", label="尺寸模式")
                    aspect_preset = gr.Dropdown(_preset_choices(ASPECT_PRESETS), value="square", label="宽高比预设")
                    pixel_budget_preset = gr.Dropdown(_preset_choices(PIXEL_BUDGET_PRESETS), value="standard", label="像素预算")
                    width = gr.Number(value=1024, precision=0, label="宽度")
                    height = gr.Number(value=1024, precision=0, label="高度")
                    size_feedback = gr.Markdown(value="解析尺寸: `1024x1024` (1,048,576 px，宽高比 1)")
                    quality = gr.Dropdown(_choices(options["quality"], QUALITY_LABELS), value="auto", label="质量")
                    output_format = gr.Dropdown(_choices(options["output_format"], OUTPUT_FORMAT_LABELS), value="png", label="输出格式")
                    output_compression_enabled = gr.Checkbox(value=False, label="启用压缩")
                    output_compression = gr.Slider(0, 100, value=80, step=1, label="输出压缩")
                    background = gr.Dropdown(_choices(options["background"], BACKGROUND_LABELS), value="auto", label="背景")
                    moderation = gr.Dropdown(_choices(options["moderation"], MODERATION_LABELS), value="auto", label="内容审核")
                    stream = gr.Checkbox(value=False, label="流式返回局部预览")
                    partial_images = gr.Dropdown(options["partial_images"], value=0, label="局部预览数量")
                    save_partials = gr.Checkbox(value=False, label="保存局部预览")

                with gr.Accordion("执行", open=False):
                    image_count = gr.Slider(1, 10, value=1, step=1, label="每个输入生成数量")
                    concurrency = gr.Slider(1, 8, value=2, step=1, label="并发数")
                    max_retries = gr.Slider(0, 5, value=2, step=1, label="最大重试次数")
                    timeout_seconds = gr.Slider(30, 600, value=240, step=1, label="超时秒数")
                    failure_policy = gr.Dropdown(_choices(["continue", "stop"], FAILURE_POLICY_LABELS), value="continue", label="失败策略")
                    overwrite_policy = gr.Dropdown(
                        _choices(["skip_existing", "overwrite", "append_counter", "new_job_dir"], OVERWRITE_POLICY_LABELS),
                        value="skip_existing",
                        label="覆盖策略",
                    )

                dry_run = gr.Button("试运行")
                with gr.Row():
                    run = gr.Button("开始运行", variant="primary")
                    pause = gr.Button("暂停")
                    cancel = gr.Button("取消")

            with gr.Column(scale=2):
                status = gr.Textbox(label="状态")
                estimate = gr.Markdown()
                current_preview = gr.Image(label="当前预览")
                gallery = gr.Gallery(label="输出结果")
                task_rows = gr.Dataframe(headers=["任务", "状态", "消息"], label="任务列表")
                usage = gr.JSON(label="实际用量")
                command_preview = gr.Code(label="命令预览")
                log_text = gr.Textbox(label="事件日志", lines=10)

        with gr.Tabs():
            with gr.Tab("历史"):
                history_root = gr.Textbox(label="输出根目录", value=str(Path.cwd() / "output-webui"))
                refresh_history = gr.Button("刷新历史")
                history_table = gr.Dataframe(
                    headers=["任务", "总数", "成功", "失败", "跳过", "路径"],
                    label="历史任务",
                )
                history_job_path = gr.Textbox(label="任务路径")
                load_history_gallery = gr.Button("加载所选任务")
                history_gallery = gr.Gallery(label="历史输出")

            with gr.Tab("设置"):
                settings_path = gr.Textbox(label="设置文件", value=str(default_settings_path()))
                with gr.Row():
                    save_settings_button = gr.Button("保存设置")
                    load_settings_button = gr.Button("加载设置")
                settings_status = gr.Textbox(label="设置状态")

        inputs = [
            mode,
            api_type,
            responses_model,
            base_url,
            proxy_url,
            api_key_source,
            api_key,
            user,
            previous_response_id,
            image_generation_call_id,
            prompt,
            input_dir,
            output_dir,
            size_mode,
            aspect_preset,
            pixel_budget_preset,
            width,
            height,
            quality,
            output_format,
            output_compression_enabled,
            output_compression,
            background,
            moderation,
            stream,
            partial_images,
            save_partials,
            image_count,
            concurrency,
            max_retries,
            timeout_seconds,
            failure_policy,
            overwrite_policy,
        ]
        outputs = [status, estimate, task_rows, log_text, gallery, current_preview, usage, command_preview]

        apply_preset.click(
            lambda preset_key, *values: _apply_preset_callback(preset_key, values),
            [scenario_preset, *inputs],
            inputs,
        )

        size_inputs = [size_mode, aspect_preset, pixel_budget_preset, width, height]
        size_outputs = [size_feedback, width, height]
        size_mode.change(validate_size_feedback, size_inputs, size_outputs)
        aspect_preset.change(validate_size_feedback, size_inputs, size_outputs)
        pixel_budget_preset.change(validate_size_feedback, size_inputs, size_outputs)
        width.change(validate_size_feedback, size_inputs, size_outputs)
        height.change(validate_size_feedback, size_inputs, size_outputs)

        dry_run.click(lambda *values: _dry_run_callback(runner, values), inputs, outputs)
        run.click(make_run_click_callback(runner), inputs, outputs)
        pause.click(lambda: pause_current_job(runner), outputs=status)
        cancel.click(lambda: cancel_current_job(runner), outputs=status)
        refresh_history.click(_history_rows, history_root, history_table)
        load_history_gallery.click(
            lambda job_path: [str(path) for path in job_gallery_paths(job_path)],
            history_job_path,
            history_gallery,
        )
        save_settings_button.click(
            lambda path, *values: _save_settings_callback(path, values),
            [settings_path, *inputs],
            settings_status,
        )
        load_settings_button.click(
            _load_settings_callback,
            settings_path,
            [settings_status, *inputs],
        )

    return demo


def _dry_run_callback(runner: WebJobRunner, values: tuple[Any, ...]):
    state = _state_from_values(values)
    return _outputs_tuple(snapshot_to_outputs(runner.dry_run(state)))


def _run_callback(runner: WebJobRunner, values: tuple[Any, ...]):
    state = _state_from_values(values)
    final_outputs = None
    for snapshot in runner.run(state):
        final_outputs = _outputs_tuple(snapshot_to_outputs(snapshot))
        yield final_outputs
    if final_outputs is None:
        yield ("无输出", "", [], "", [], None, None, "")


def make_run_click_callback(runner: WebJobRunner):
    def run_click_callback(*values: Any):
        yield from _run_callback(runner, values)

    return run_click_callback


def _apply_preset_callback(preset_key: str, values: tuple[Any, ...]) -> tuple[Any, ...]:
    values_by_name = dict(zip(INPUT_NAMES, values))
    updated = apply_scenario_preset_to_values(preset_key, values_by_name)
    return tuple(updated[name] for name in INPUT_NAMES)


def _save_settings_callback(path: str, values: tuple[Any, ...]) -> str:
    state = _state_from_values(values)
    saved_path = save_settings(Path(path), state)
    return f"设置已保存: {saved_path}"


def _load_settings_callback(path: str) -> tuple[Any, ...]:
    state = load_settings(Path(path))
    return (f"设置已加载: {path}", *_values_from_state(state))


def _history_rows(output_root: str) -> list[list[str]]:
    return [
        [
            row["job_id"],
            row["total"],
            row["succeeded"],
            row["failed"],
            row["skipped"],
            row["path"],
        ]
        for row in list_history(output_root)
    ]


def _state_from_values(values: tuple[Any, ...]) -> WebFormState:
    return build_state_from_ui(**dict(zip(INPUT_NAMES, values)))


def _values_from_state(state: WebFormState) -> tuple[Any, ...]:
    return (
        state.mode,
        state.api_type,
        state.responses_model,
        state.base_url or "",
        state.proxy_url or "",
        state.api_key_source,
        "",
        state.user or "",
        state.previous_response_id or "",
        state.image_generation_call_id or "",
        state.prompt,
        str(state.input_dir or ""),
        str(state.output_dir or ""),
        state.size_mode,
        state.aspect_preset,
        state.pixel_budget_preset,
        state.width,
        state.height,
        state.quality,
        state.output_format,
        state.output_compression is not None,
        state.output_compression if state.output_compression is not None else 80,
        state.background,
        state.moderation,
        state.stream,
        state.partial_images,
        state.save_partials,
        state.image_count,
        state.concurrency,
        state.max_retries,
        state.timeout_seconds,
        state.failure_policy,
        state.overwrite_policy,
    )


def _outputs_tuple(outputs: GradioOutputs) -> tuple[Any, ...]:
    return (
        outputs.status,
        outputs.estimate_markdown,
        outputs.task_rows,
        outputs.log_text,
        outputs.gallery,
        outputs.current_preview,
        outputs.usage,
        outputs.command_preview,
    )


def _optional_path(value: str) -> Path | None:
    stripped = value.strip()
    return Path(stripped) if stripped else None


def _preview_image(b64_json: str | None):
    if not b64_json:
        return None
    from PIL import Image

    return Image.open(BytesIO(base64.b64decode(b64_json)))


def _coerce_int(value: int | float | None, default: int) -> int:
    if value is None:
        return default
    return int(value)


def _token_impact(total_tokens: int) -> str:
    if total_tokens < 1_000:
        return "低"
    if total_tokens < 4_000:
        return "中"
    return "高"


def scenario_preset_choices() -> list[tuple[str, str]]:
    return [(preset.label, key) for key, preset in SCENARIO_PRESETS.items()]


def _preset_choices(presets: dict[str, Any]) -> list[tuple[str, str]]:
    return [(preset.label, key) for key, preset in presets.items()]


def _choices(values: list[Any], labels: dict[str, str]) -> list[tuple[str, Any]]:
    return [(labels.get(str(value), str(value)), value) for value in values]


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def _snapshot_status_label(snapshot: WebJobSnapshot) -> str:
    label = _status_label(snapshot.status)
    connectivity_message = _connectivity_message(snapshot.event_log)
    if snapshot.status == "dry_run" and connectivity_message:
        return f"{label}；{connectivity_message}"
    return label


def _connectivity_message(event_log: list[str]) -> str | None:
    for line in event_log:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("event") == "connectivity_check":
            message = record.get("message")
            return str(message) if message else None
    return None


_CSS = """
.gradio-container { max-width: 1400px !important; }
"""


__all__ = [
    "GradioOutputs",
    "apply_scenario_preset_to_values",
    "build_demo",
    "build_state_from_ui",
    "cancel_current_job",
    "format_estimate_markdown",
    "make_run_click_callback",
    "pause_current_job",
    "scenario_preset_choices",
    "snapshot_to_outputs",
    "validate_size_feedback",
]
