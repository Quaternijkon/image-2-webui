from __future__ import annotations

import json
from typing import Any


class ImageBatchError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        fatal: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.fatal = fatal
        self.details = details or {}


def classify_exception(exc: BaseException) -> ImageBatchError:
    if isinstance(exc, ImageBatchError):
        return exc

    status_code = getattr(exc, "status_code", None)
    error_code = str(getattr(exc, "code", "") or getattr(exc, "type", "") or "").lower()
    message = str(exc) or exc.__class__.__name__
    lower_message = message.lower()
    payload = _exception_payload(exc)
    payload_text = _payload_text(payload).lower()
    combined = " ".join(part for part in [error_code, lower_message, payload_text] if part)

    if any(
        token in combined
        for token in [
            "stream error",
            "internal_error",
            "empty_stream",
            "upstream stream closed",
            "received from peer",
        ]
    ):
        return ImageBatchError("server_error", message, retryable=True)
    if status_code == 402 or any(
        token in combined
        for token in [
            "deactivated_workspace",
            "workspace deactivated",
            "payment required",
            "insufficient quota",
            "insufficient_quota",
        ]
    ):
        return ImageBatchError("account_unavailable", message, retryable=False, fatal=True)
    if status_code == 429 or "rate limit" in combined:
        return ImageBatchError("rate_limit", message, retryable=True)
    if "timeout" in combined or exc.__class__.__name__.lower().endswith("timeout"):
        return ImageBatchError("timeout", message, retryable=True)
    if "bad_response_body" in combined or "invalid character" in combined:
        return ImageBatchError(
            "gateway_response",
            f"{message}. The gateway returned a non-JSON/unsupported response shape.",
            retryable=False,
        )
    if status_code and 500 <= int(status_code) <= 599:
        return ImageBatchError("server_error", message, retryable=True)
    if any(token in combined for token in ["connection", "network", "temporarily unavailable"]):
        return ImageBatchError("network_error", message, retryable=True)
    if status_code in {401, 403} or "auth" in error_code or "api key" in lower_message:
        return ImageBatchError("auth", message, retryable=False, fatal=True)
    if any(
        token in combined
        for token in [
            "content_policy",
            "content policy",
            "content_filter",
            "content filter",
            "safety",
            "moderation",
            "policy_violation",
        ]
    ):
        return ImageBatchError("content_policy", message, retryable=False)
    if status_code and 400 <= int(status_code) <= 499:
        return ImageBatchError("invalid_request", message, retryable=False)

    return ImageBatchError("unknown_error", message, retryable=False)


def _exception_payload(exc: BaseException) -> Any:
    for attr in ("body", "error", "details"):
        payload = getattr(exc, attr, None)
        if payload:
            return payload

    response = getattr(exc, "response", None)
    if response is not None:
        json_method = getattr(response, "json", None)
        if callable(json_method):
            try:
                return json_method()
            except Exception:
                return None
        return response

    return None


def _payload_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(_payload_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_payload_text(item) for item in value)
    if hasattr(value, "model_dump"):
        try:
            return _payload_text(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return _payload_text(vars(value))
    try:
        return json.dumps(value, ensure_ascii=True, default=str)
    except TypeError:
        return str(value)


__all__ = ["ImageBatchError", "classify_exception"]
