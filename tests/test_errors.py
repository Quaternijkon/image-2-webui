import unittest

from app.core.errors import classify_exception


class ErrorClassificationTests(unittest.TestCase):
    def test_structured_content_policy_body_is_content_policy_error(self):
        exc = _ApiError(
            400,
            "Error code: 400",
            body={
                "error": {
                    "message": "Your request was rejected by the safety system.",
                    "type": "invalid_request_error",
                    "code": "content_policy_violation",
                }
            },
        )

        error = classify_exception(exc)

        self.assertEqual(error.code, "content_policy")
        self.assertFalse(error.retryable)
        self.assertFalse(error.fatal)

    def test_deactivated_workspace_402_is_fatal_account_error(self):
        exc = _ApiError(
            402,
            "Error code: 402 - {'detail': {'code': 'deactivated_workspace'}}",
        )

        error = classify_exception(exc)

        self.assertEqual(error.code, "account_unavailable")
        self.assertFalse(error.retryable)
        self.assertTrue(error.fatal)

    def test_stream_internal_error_is_retryable_server_error(self):
        error = classify_exception(Exception("stream error: stream ID 13; INTERNAL_ERROR; received from peer"))

        self.assertEqual(error.code, "server_error")
        self.assertTrue(error.retryable)
        self.assertFalse(error.fatal)


class _ApiError(Exception):
    def __init__(self, status_code: int, message: str, *, body=None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


if __name__ == "__main__":
    unittest.main()
