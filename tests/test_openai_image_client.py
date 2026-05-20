import sys
import types
import unittest
from unittest.mock import patch

from app.core.config import AppConfig
from app.core.errors import ImageBatchError
from app.core.openai_image_client import OpenAIImageClient, _collect_responses_response, _collect_stream


class OpenAIImageClientTests(unittest.TestCase):
    def test_sdk_client_uses_configured_proxy_url(self):
        captured: dict[str, object] = {}

        class FakeHttpClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        config = AppConfig(
            api={
                "api_type": "image",
                "base_url": "http://example.test",
                "api_key": "secret-key",
                "api_key_source": "env",
                "proxy_url": "http://127.0.0.1:10808",
            },
            prompt={"template": "test"},
            output={"output_dir": "output-webui"},
        )

        with patch.dict(sys.modules, {"openai": types.SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI)}):
            with patch("httpx.AsyncClient", FakeHttpClient):
                OpenAIImageClient(config).sdk_client

        self.assertEqual(captured["api_key"], "secret-key")
        self.assertEqual(captured["base_url"], "http://example.test/v1")
        self.assertEqual(captured["max_retries"], 0)
        http_client = captured["http_client"]
        self.assertIsInstance(http_client, FakeHttpClient)
        self.assertEqual(http_client.kwargs["proxy"], "http://127.0.0.1:10808")
        self.assertFalse(http_client.kwargs["trust_env"])

    def test_responses_refusal_is_content_policy_error(self):
        response = types.SimpleNamespace(
            status="completed",
            output=[
                types.SimpleNamespace(
                    type="message",
                    content=[
                        types.SimpleNamespace(
                            type="refusal",
                            refusal="I cannot help generate that image.",
                        )
                    ],
                )
            ],
        )

        with self.assertRaises(ImageBatchError) as raised:
            _collect_responses_response(response)

        self.assertEqual(raised.exception.code, "content_policy")

    def test_responses_content_filter_incomplete_is_content_policy_error(self):
        response = types.SimpleNamespace(
            status="incomplete",
            incomplete_details=types.SimpleNamespace(reason="content_filter"),
            output=[],
        )

        with self.assertRaises(ImageBatchError) as raised:
            _collect_responses_response(response)

        self.assertEqual(raised.exception.code, "content_policy")

    def test_stream_failed_event_with_policy_error_is_content_policy_error(self):
        response = _AsyncEvents(
            [
                {
                    "type": "response.failed",
                    "response": {
                        "error": {
                            "code": "content_policy_violation",
                            "message": "Rejected by safety policy.",
                        }
                    },
                }
            ]
        )

        with self.assertRaises(ImageBatchError) as raised:
            import asyncio

            asyncio.run(_collect_stream(response))

        self.assertEqual(raised.exception.code, "content_policy")


class _AsyncEvents:
    def __init__(self, events):
        self._events = events

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


if __name__ == "__main__":
    unittest.main()
