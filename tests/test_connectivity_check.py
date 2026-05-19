import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request

from app.core.config import AppConfig
from app.core.connectivity_check import check_api_connectivity


class ConnectivityCheckTests(unittest.TestCase):
    def test_check_uses_models_endpoint_with_authorization_header(self):
        seen: dict[str, object] = {}

        def transport(request: Request, timeout: float):
            seen["url"] = request.full_url
            seen["auth"] = request.get_header("Authorization")
            seen["timeout"] = timeout
            return _Response(200, b'{"data":[]}')

        result = check_api_connectivity(
            _config(base_url="http://example.test/v1", api_key="secret-key"),
            timeout_seconds=3,
            transport=transport,
        )

        self.assertTrue(result.reachable)
        self.assertTrue(result.ok)
        self.assertEqual(result.url, "http://example.test/v1/models")
        self.assertEqual(result.method, "GET")
        self.assertEqual(seen["url"], "http://example.test/v1/models")
        self.assertEqual(seen["auth"], "Bearer secret-key")
        self.assertEqual(seen["timeout"], 3)

    def test_check_reports_network_error_without_leaking_api_key(self):
        def transport(request: Request, timeout: float):
            raise URLError("timed out with secret-key")

        result = check_api_connectivity(
            _config(base_url="http://example.test/v1", api_key="secret-key"),
            transport=transport,
        )

        self.assertFalse(result.reachable)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "network_error")
        self.assertIn("联通失败", result.message)
        self.assertNotIn("secret-key", result.message)

    def test_check_treats_auth_failure_as_reachable_service(self):
        def transport(request: Request, timeout: float):
            raise HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                hdrs=None,
                fp=None,
            )

        result = check_api_connectivity(
            _config(base_url="http://example.test/v1", api_key="bad-key"),
            transport=transport,
        )

        self.assertTrue(result.reachable)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "auth_failed")
        self.assertIn("鉴权失败", result.message)


def _config(*, base_url: str, api_key: str) -> AppConfig:
    return AppConfig(
        api={
            "api_type": "image",
            "base_url": base_url,
            "api_key": api_key,
            "api_key_source": "env",
        },
        prompt={"template": "test"},
        output={"output_dir": "output-webui"},
    )


class _Response:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit: int = -1) -> bytes:
        return self.body[:limit]


if __name__ == "__main__":
    unittest.main()
