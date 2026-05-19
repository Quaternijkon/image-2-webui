from __future__ import annotations

from typing import Any


class ImageBatchError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


def classify_exception(exc: BaseException) -> ImageBatchError:
    if isinstance(exc, ImageBatchError):
        return exc

    status_code = getattr(exc, "status_code", None)
    error_code = str(getattr(exc, "code", "") or getattr(exc, "type", "") or "").lower()
    message = str(exc) or exc.__class__.__name__
    lower_message = message.lower()

    if status_code == 429 or "rate limit" in lower_message:
        return ImageBatchError("rate_limit", message, retryable=True)
    if "timeout" in lower_message or exc.__class__.__name__.lower().endswith("timeout"):
        return ImageBatchError("timeout", message, retryable=True)
    if "bad_response_body" in error_code or "invalid character" in lower_message:
        return ImageBatchError(
            "gateway_response",
            f"{message}. The gateway returned a non-JSON/unsupported response shape.",
            retryable=False,
        )
    if status_code and 500 <= int(status_code) <= 599:
        return ImageBatchError("server_error", message, retryable=True)
    if any(token in lower_message for token in ["connection", "network", "temporarily unavailable"]):
        return ImageBatchError("network_error", message, retryable=True)
    if status_code in {401, 403} or "auth" in error_code or "api key" in lower_message:
        return ImageBatchError("auth", message, retryable=False)
    if "content_policy" in error_code or "content policy" in lower_message or "safety" in lower_message:
        return ImageBatchError("content_policy", message, retryable=False)
    if status_code and 400 <= int(status_code) <= 499:
        return ImageBatchError("invalid_request", message, retryable=False)

    return ImageBatchError("unknown_error", message, retryable=False)


__all__ = ["ImageBatchError", "classify_exception"]
