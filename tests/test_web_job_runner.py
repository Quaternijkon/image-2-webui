import unittest

from app.core.connectivity_check import ConnectivityCheckResult
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


if __name__ == "__main__":
    unittest.main()
