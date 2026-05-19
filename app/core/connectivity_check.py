from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from time import monotonic
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.core.config import AppConfig


Transport = Callable[[Request, float], object]


@dataclass(frozen=True)
class ConnectivityCheckResult:
    ok: bool
    reachable: bool
    code: str
    message: str
    method: str
    url: str
    status_code: int | None = None
    elapsed_ms: int | None = None

    def to_event(self) -> dict[str, object]:
        return {"event": "connectivity_check", **asdict(self)}


def check_api_connectivity(
    config: AppConfig,
    *,
    timeout_seconds: float = 8,
    transport: Transport | None = None,
) -> ConnectivityCheckResult:
    method = "GET"
    url = _models_url(config.api.base_url)
    transport = transport or _urlopen_transport
    started = monotonic()

    request = Request(url, method=method, headers=_headers(config.api.api_key))
    try:
        response = transport(request, timeout_seconds)
        status_code = int(getattr(response, "status", 200))
        with response:
            _read_probe_body(response)
    except HTTPError as exc:
        return _http_error_result(
            exc,
            method=method,
            url=url,
            elapsed_ms=_elapsed_ms(started),
        )
    except (OSError, URLError, TimeoutError) as exc:
        return ConnectivityCheckResult(
            ok=False,
            reachable=False,
            code="network_error",
            message=f"联通失败：无法连接到 API 服务（{_safe_error_message(exc, config.api.api_key)}）。",
            method=method,
            url=url,
            elapsed_ms=_elapsed_ms(started),
        )

    if 200 <= status_code < 300:
        return ConnectivityCheckResult(
            ok=True,
            reachable=True,
            code="ok",
            message="联通检测通过：API 服务可访问，/models 返回成功。",
            method=method,
            url=url,
            status_code=status_code,
            elapsed_ms=_elapsed_ms(started),
        )

    return ConnectivityCheckResult(
        ok=False,
        reachable=True,
        code="http_error",
        message=f"API 服务可访问，但 /models 返回 HTTP {status_code}。",
        method=method,
        url=url,
        status_code=status_code,
        elapsed_ms=_elapsed_ms(started),
    )


def format_connectivity_event(result: ConnectivityCheckResult) -> str:
    return json.dumps(result.to_event(), ensure_ascii=False, sort_keys=True)


def _http_error_result(
    exc: HTTPError,
    *,
    method: str,
    url: str,
    elapsed_ms: int,
) -> ConnectivityCheckResult:
    status_code = int(exc.code)
    if status_code in {401, 403}:
        return ConnectivityCheckResult(
            ok=False,
            reachable=True,
            code="auth_failed",
            message=f"API 服务可访问，但鉴权失败（HTTP {status_code}）。请检查 API Key。",
            method=method,
            url=url,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
        )

    return ConnectivityCheckResult(
        ok=False,
        reachable=True,
        code="http_error",
        message=f"API 服务可访问，但 /models 返回 HTTP {status_code}。",
        method=method,
        url=url,
        status_code=status_code,
        elapsed_ms=elapsed_ms,
    )


def _headers(api_key: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _models_url(base_url: str | None) -> str:
    normalized = _normalize_base_url(base_url or "https://api.openai.com/v1")
    return f"{normalized}/models"


def _normalize_base_url(value: str) -> str:
    stripped = value.strip().rstrip("/")
    parsed = urlsplit(stripped)
    if parsed.scheme in {"http", "https"} and parsed.netloc and parsed.path in {"", "/"}:
        return urlunsplit((parsed.scheme, parsed.netloc, "/v1", "", ""))
    return stripped


def _urlopen_transport(request: Request, timeout: float) -> object:
    return urlopen(request, timeout=timeout)


def _read_probe_body(response: object) -> None:
    read = getattr(response, "read", None)
    if callable(read):
        read(1024)


def _elapsed_ms(started: float) -> int:
    return int((monotonic() - started) * 1000)


def _safe_error_message(exc: BaseException, api_key: str | None) -> str:
    text = str(exc) or exc.__class__.__name__
    if api_key:
        text = text.replace(api_key, "[redacted]")
    return text.replace("\n", " ")[:240]


__all__ = [
    "ConnectivityCheckResult",
    "check_api_connectivity",
    "format_connectivity_event",
]
