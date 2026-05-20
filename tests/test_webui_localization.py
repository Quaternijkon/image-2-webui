import unittest
from pathlib import Path
from inspect import isgeneratorfunction

from app.core.cost_estimator import CostEstimate
from app.webui.gradio_app import (
    INPUT_NAMES,
    build_state_from_ui,
    format_estimate_markdown,
    make_run_click_callback,
    snapshot_to_outputs,
    scenario_preset_choices,
    validate_size_feedback,
)
from app.webui.job_runner import WebJobSnapshot


class WebUiLocalizationTests(unittest.TestCase):
    def test_estimate_markdown_uses_chinese_labels(self):
        estimate = CostEstimate(
            estimated=True,
            task_count=2,
            estimated_output_images=2,
            estimated_partial_images=1,
            estimated_prompt_tokens=12,
            estimated_input_image_tokens=34,
            estimated_output_image_tokens=56,
            estimated_partial_image_tokens=78,
            estimated_total_tokens=180,
            estimated_image_token_units=56,
            estimated_total_token_units=180,
            cost_usd=None,
            note="official API usage is authoritative",
        )

        markdown = format_estimate_markdown(estimate)

        self.assertIn("### Token 预估", markdown)
        self.assertIn("影响等级: `低`", markdown)
        self.assertIn("任务数: `2`", markdown)
        self.assertIn("预估提示词 token: `12`", markdown)

    def test_size_feedback_uses_chinese_labels(self):
        message, width, height = validate_size_feedback("preset", "square", "standard", 1024, 1024)

        self.assertEqual((width, height), (1024, 1024))
        self.assertIn("解析尺寸", message)
        self.assertIn("宽高比", message)

    def test_scenario_choices_show_chinese_labels_but_keep_internal_keys(self):
        choices = scenario_preset_choices()

        self.assertIn(("均衡预览", "balanced_preview"), choices)
        self.assertIn(("批量编辑", "batch_edit"), choices)

    def test_build_state_includes_responses_multi_turn_fields(self):
        kwargs = dict(zip(INPUT_NAMES, _default_input_values()))

        state = build_state_from_ui(**kwargs)

        self.assertEqual(state.responses_model, "gpt-5.5")
        self.assertEqual(state.user, "tester")
        self.assertEqual(state.previous_response_id, "resp_123")
        self.assertEqual(state.image_generation_call_id, "igc_456")

    def test_build_state_includes_proxy_url(self):
        self.assertIn("proxy_url", INPUT_NAMES)
        kwargs = dict(zip(INPUT_NAMES, _default_input_values()))
        kwargs["proxy_url"] = "http://127.0.0.1:10808"

        state = build_state_from_ui(**kwargs)
        config = state.build_config()

        self.assertEqual(state.proxy_url, "http://127.0.0.1:10808")
        self.assertEqual(config.api.proxy_url, "http://127.0.0.1:10808")

    def test_run_click_callback_is_gradio_streaming_generator(self):
        callback = make_run_click_callback(_FakeRunner())

        self.assertTrue(isgeneratorfunction(callback))
        first_output = next(callback(*_default_input_values()))

        self.assertEqual(len(first_output), 8)
        self.assertEqual(first_output[0], "运行中")

    def test_connectivity_check_event_is_shown_in_log_text(self):
        outputs = snapshot_to_outputs(
            WebJobSnapshot(
                status="dry_run",
                job_root=Path("job"),
                summary={"total_tasks": 1, "issues": 0},
                estimate=_estimate(),
                event_log=[
                    '{"event":"connectivity_check","message":"联通检测通过","ok":true}'
                ],
            )
        )

        self.assertIn("connectivity_check", outputs.log_text)
        self.assertIn("联通检测通过", outputs.log_text)

    def test_dry_run_status_includes_connectivity_message(self):
        outputs = snapshot_to_outputs(
            WebJobSnapshot(
                status="dry_run",
                job_root=Path("job"),
                summary={"total_tasks": 1, "issues": 0},
                estimate=_estimate(),
                event_log=[
                    '{"event":"connectivity_check","message":"联通失败：无法连接到 API 服务。","ok":false}'
                ],
            )
        )

        self.assertIn("试运行完成", outputs.status)
        self.assertIn("联通失败", outputs.status)


def _default_input_values():
    return [
        "generate",
        "responses",
        "gpt-5.5",
        "",
        "",
        "env",
        "",
        "tester",
        "resp_123",
        "igc_456",
        "生成一张清晰、干净的图片。",
        "",
        "output-webui",
        "preset",
        "square",
        "standard",
        1024,
        1024,
        "auto",
        "png",
        False,
        80,
        "auto",
        "auto",
        False,
        0,
        False,
        1,
        2,
        2,
        240,
        "continue",
        "skip_existing",
    ]


class _FakeRunner:
    def run(self, state):
        yield WebJobSnapshot(
            status="running",
            job_root=Path("job"),
            summary={"total_tasks": 1, "issues": 0},
            estimate=CostEstimate(
                **_estimate().model_dump()
            ),
        )


def _estimate() -> CostEstimate:
    return CostEstimate(
        estimated=True,
        task_count=1,
        estimated_output_images=1,
        estimated_partial_images=0,
        estimated_prompt_tokens=1,
        estimated_input_image_tokens=0,
        estimated_output_image_tokens=1,
        estimated_partial_image_tokens=0,
        estimated_total_tokens=2,
        estimated_image_token_units=1,
        estimated_total_token_units=2,
        cost_usd=None,
        note="test estimate",
    )


if __name__ == "__main__":
    unittest.main()
