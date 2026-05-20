import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.connectivity_check import ConnectivityCheckResult
from app.core.openai_image_client import DeterministicMockImageClient
from app.webui.job_runner import WebJobRunner
from app.webui.state import WebFormState


class WebJobRunnerTests(unittest.TestCase):
    def test_dry_run_records_connectivity_check_event(self):
        runner = WebJobRunner(connectivity_checker=lambda config: ConnectivityCheckResult(
            ok=False,
            reachable=False,
            code="network_error",
            message="联通失败：无法连接到 API 服务。",
            method="GET",
            url="http://example.test/v1/models",
            elapsed_ms=123,
        ))

        snapshot = runner.dry_run(WebFormState(prompt="生成一张测试图片。"))

        self.assertEqual(len(snapshot.event_log), 1)
        self.assertIn("connectivity_check", snapshot.event_log[0])
        self.assertIn("network_error", snapshot.event_log[0])
        self.assertIn("example.test/v1/models", snapshot.event_log[0])

    def test_run_ignores_stale_cancel_control_file_from_previous_job(self):
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            control_path = output_dir / "job.control.json"
            control_path.write_text('{"cancel_requested": true}\n', encoding="utf-8")

            runner = WebJobRunner(client_factory=lambda config: DeterministicMockImageClient())
            snapshots = list(
                runner.run(
                    WebFormState(
                        prompt="生成一张测试图片。",
                        output_dir=output_dir,
                        concurrency=1,
                        image_count=1,
                    )
                )
            )

            final = snapshots[-1]
            self.assertEqual(final.summary["succeeded"], 1)
            self.assertEqual(final.summary["canceled"], 0)
            self.assertFalse(control_path.exists())


if __name__ == "__main__":
    unittest.main()
