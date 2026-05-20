import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.connectivity_check import ConnectivityCheckResult
from app.core.openai_image_client import CompletedImage, DeterministicMockImageClient, PartialImage
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

    def test_run_stops_after_fatal_account_error(self):
        with TemporaryDirectory() as temp_dir:
            runner = WebJobRunner(client_factory=lambda config: _DeactivatedWorkspaceClient())
            snapshots = list(
                runner.run(
                    WebFormState(
                        prompt="生成一张测试图片。",
                        output_dir=Path(temp_dir),
                        concurrency=1,
                        image_count=3,
                    )
                )
            )

            final = snapshots[-1]
            self.assertEqual(final.summary["failed"], 1)
            self.assertEqual(final.summary["stopped"], 2)

    def test_run_retries_stream_that_ends_before_completed_image(self):
        with TemporaryDirectory() as temp_dir:
            client = _PartialThenCompletedClient()
            runner = WebJobRunner(client_factory=lambda config: client)
            snapshots = list(
                runner.run(
                    WebFormState(
                        prompt="生成一张测试图片。",
                        output_dir=Path(temp_dir),
                        concurrency=1,
                        image_count=1,
                        max_retries=1,
                    )
                )
            )

            final = snapshots[-1]
            self.assertEqual(client.calls, 2)
            self.assertEqual(final.summary["succeeded"], 1)
            self.assertEqual(final.summary["failed"], 0)

    def test_run_retries_stream_internal_error(self):
        with TemporaryDirectory() as temp_dir:
            client = _StreamErrorThenCompletedClient()
            runner = WebJobRunner(client_factory=lambda config: client)
            snapshots = list(
                runner.run(
                    WebFormState(
                        prompt="生成一张测试图片。",
                        output_dir=Path(temp_dir),
                        concurrency=1,
                        image_count=1,
                        max_retries=1,
                    )
                )
            )

            final = snapshots[-1]
            self.assertEqual(client.calls, 2)
            self.assertEqual(final.summary["succeeded"], 1)
            self.assertEqual(final.summary["failed"], 0)


class _DeactivatedWorkspaceClient:
    async def run_task(self, task):
        raise _ApiError(402, "Error code: 402 - {'detail': {'code': 'deactivated_workspace'}}")


class _PartialThenCompletedClient:
    def __init__(self) -> None:
        self.calls = 0

    async def run_task(self, task):
        self.calls += 1
        if self.calls == 1:
            return [PartialImage(index=0, b64_json=_PNG_B64)]
        return [CompletedImage(b64_json=_PNG_B64, usage={"retry": True})]


class _StreamErrorThenCompletedClient:
    def __init__(self) -> None:
        self.calls = 0

    async def run_task(self, task):
        self.calls += 1
        if self.calls == 1:
            raise Exception("stream error: stream ID 13; INTERNAL_ERROR; received from peer")
        return [CompletedImage(b64_json=_PNG_B64, usage={"retry": True})]


class _ApiError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="


if __name__ == "__main__":
    unittest.main()
