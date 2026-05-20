import sys
import types
import unittest
from unittest.mock import patch

from app.core.config import AppConfig
from app.core.openai_image_client import OpenAIImageClient


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


if __name__ == "__main__":
    unittest.main()
