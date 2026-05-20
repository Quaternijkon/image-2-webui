from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from time import monotonic
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import ProxyHandler, Request, build_opener, urlopen

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
    endpoint_probe: bool = False,
) -> ConnectivityCheckResult:
    method = "GET"
    url = _models_url(config.api.base_url)
    transport = transport or _transport_for_proxy(config.api.proxy_url)
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
        if endpoint_probe:
            endpoint_result = _check_generation_endpoint(config, transport, timeout_seconds, started)
            if endpoint_result is not None:
                return endpoint_result
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


def _check_generation_endpoint(
    config: AppConfig,
    transport: Transport,
    timeout_seconds: float,
    started: float,
) -> ConnectivityCheckResult | None:
    method = "POST"
    url = _generation_probe_url(config)
    headers = _headers(config.api.api_key)
    headers["Content-Type"] = "application/json"
    request = Request(url, data=b"{}", method=method, headers=headers)
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
            endpoint_probe=True,
        )
    except (OSError, URLError, TimeoutError) as exc:
        return ConnectivityCheckResult(
            ok=False,
            reachable=False,
            code="network_error",
            message=f"生成端点联通失败：无法连接到 API 服务（{_safe_error_message(exc, config.api.api_key)}）。",
            method=method,
            url=url,
            elapsed_ms=_elapsed_ms(started),
        )

    if 200 <= status_code < 300:
        return ConnectivityCheckResult(
            ok=True,
            reachable=True,
            code="ok",
            message="联通检测通过：API 服务和生成端点均可访问。",
            method=method,
            url=url,
            status_code=status_code,
            elapsed_ms=_elapsed_ms(started),
        )

    return ConnectivityCheckResult(
        ok=False,
        reachable=True,
        code="http_error",
        message=f"API 服务可访问，但生成端点返回 HTTP {status_code}。",
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
    endpoint_probe: bool = False,
) -> ConnectivityCheckResult:
    status_code = int(exc.code)
    body = _http_error_body(exc)
    if _is_account_unavailable(status_code, body, str(exc)):
        return ConnectivityCheckResult(
            ok=False,
            reachable=True,
            code="account_unavailable",
            message=f"API 服务可访问，但账号、工作区或计费状态不可用（HTTP {status_code}）。请检查 API Key 对应的工作区状态。",
            method=method,
            url=url,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
        )
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

    if endpoint_probe and status_code in {400, 422}:
        return ConnectivityCheckResult(
            ok=True,
            reachable=True,
            code="ok",
            message="联通检测通过：/models 可访问，生成端点已通过鉴权；无效探测请求按预期返回参数错误。",
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


def _generation_probe_url(config: AppConfig) -> str:
    normalized = _normalize_base_url(config.api.base_url or "https://api.openai.com/v1")
    if config.api.api_type == "responses":
        return f"{normalized}/responses"
    return f"{normalized}/images/generations"


def _normalize_base_url(value: str) -> str:
    stripped = value.strip().rstrip("/")
    parsed = urlsplit(stripped)
    if parsed.scheme in {"http", "https"} and parsed.netloc and parsed.path in {"", "/"}:
        return urlunsplit((parsed.scheme, parsed.netloc, "/v1", "", ""))
    return stripped


def _transport_for_proxy(proxy_url: str | None) -> Transport:
    if not proxy_url:
        return _urlopen_transport
    opener = build_opener(ProxyHandler({"http": proxy_url, "https": proxy_url}))
    return lambda request, timeout: opener.open(request, timeout=timeout)


def _urlopen_transport(request: Request, timeout: float) -> object:
    return urlopen(request, timeout=timeout)


def _read_probe_body(response: object) -> None:
    read = getattr(response, "read", None)
    if callable(read):
        read(1024)


def _http_error_body(exc: HTTPError) -> str:
    fp = getattr(exc, "fp", None)
    if fp is None:
        return ""
    try:
        raw = fp.read(2048)
    except Exception:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return str(raw)


def _is_account_unavailable(status_code: int, body: str, message: str) -> bool:
    text = f"{body} {message}".lower()
    return status_code == 402 or any(
        token in text
        for token in [
            "deactivated_workspace",
            "workspace deactivated",
            "payment required",
            "insufficient quota",
            "insufficient_quota",
        ]
    )


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
