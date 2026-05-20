from __future__ import annotations

import base64
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from app.core.api_capabilities import get_model_capabilities, mode_to_responses_action
from app.core.config import AppConfig
from app.core.errors import ImageBatchError, classify_exception
from app.core.models import TaskPlan


@dataclass(frozen=True)
class CompletedImage:
    b64_json: str
    usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class PartialImage:
    index: int
    b64_json: str


ImageClientResult = list[CompletedImage | PartialImage]


class ImageClient(Protocol):
    async def run_task(self, task: TaskPlan) -> ImageClientResult:
        ...


class OpenAIImageClient:
    def __init__(self, config: AppConfig, *, sdk_client: Any | None = None) -> None:
        self.config = config
        self._sdk_client = sdk_client

    async def run_task(self, task: TaskPlan) -> ImageClientResult:
        try:
            if self.config.api.api_type == "responses":
                return await self._responses(task)
            try:
                if task.mode == "generate":
                    return await self._generate(task)
                return await self._edit(task)
            except Exception as image_exc:
                error = classify_exception(image_exc)
                if self.config.image.stream and error.code == "gateway_response":
                    return await self._responses(task)
                raise error from image_exc
        except Exception as exc:
            raise classify_exception(exc) from exc

    @property
    def sdk_client(self) -> Any:
        if self._sdk_client is None:
            api_key = _resolve_api_key(self.config)
            from openai import AsyncOpenAI

            kwargs = {"max_retries": 0}
            if api_key is not None:
                kwargs["api_key"] = api_key
            base_url = _resolve_base_url(self.config)
            if base_url:
                kwargs["base_url"] = base_url
            if self.config.api.proxy_url:
                import httpx

                kwargs["http_client"] = httpx.AsyncClient(
                    proxy=self.config.api.proxy_url,
                    trust_env=False,
                )
            self._sdk_client = AsyncOpenAI(**kwargs)
        return self._sdk_client

    async def _generate(self, task: TaskPlan) -> ImageClientResult:
        params = self._image_api_params(task, endpoint="generations")
        if self.config.image.stream:
            response = await self.sdk_client.images.generate(**params)
            return await _collect_stream(response)
        response = await self.sdk_client.images.generate(**params)
        return await _collect_non_stream(response)

    async def _edit(self, task: TaskPlan) -> ImageClientResult:
        params = self._image_api_params(task, endpoint="edits")
        handles = []
        try:
            for source_path in task.source_paths:
                handle = source_path.open("rb")
                handles.append(handle)
            params["image"] = handles
            if task.mask_path is not None:
                mask = task.mask_path.open("rb")
                handles.append(mask)
                params["mask"] = mask
            if self.config.image.stream:
                response = await self.sdk_client.images.edit(**params)
                return await _collect_stream(response)
            response = await self.sdk_client.images.edit(**params)
            return await _collect_non_stream(response)
        finally:
            for handle in handles:
                handle.close()

    async def _responses(self, task: TaskPlan) -> ImageClientResult:
        params: dict[str, Any] = {
            "model": self.config.api.responses_model,
            "input": self._responses_input(task),
            "tools": [self._responses_image_generation_tool(task)],
            "timeout": self.config.execution.timeout_seconds,
        }
        if self.config.image.stream:
            params["stream"] = True
        if self.config.api.previous_response_id:
            params["previous_response_id"] = self.config.api.previous_response_id
        if self.config.api.user:
            params["user"] = self.config.api.user

        response = await self.sdk_client.responses.create(**params)
        if self.config.image.stream:
            return await _collect_stream(response)
        return _collect_responses_response(response)

    def _image_api_params(self, task: TaskPlan, *, endpoint: str) -> dict[str, Any]:
        image_config = self.config.image
        capabilities = get_model_capabilities(self.config.api.model)
        params: dict[str, Any] = {
            "model": self.config.api.model,
            "n": 1,
            "timeout": self.config.execution.timeout_seconds,
            "prompt": task.rendered_prompt,
        }

        if _should_send_size(capabilities, image_config.size):
            params["size"] = image_config.size
        if _should_send_quality(capabilities, image_config.quality):
            params["quality"] = image_config.quality
        if _is_supported(capabilities, "output_formats", image_config.output_format):
            params["output_format"] = image_config.output_format
        if _is_supported(capabilities, "backgrounds", image_config.background):
            params["background"] = image_config.background
        if endpoint == "generations" and _is_supported(capabilities, "moderations", image_config.moderation):
            params["moderation"] = image_config.moderation
        if endpoint == "edits" and _is_supported(capabilities, "moderations", image_config.moderation):
            params["extra_body"] = {"moderation": image_config.moderation}
        if self.config.api.user:
            params["user"] = self.config.api.user
        if image_config.output_compression is not None and image_config.output_format != "png":
            params["output_compression"] = image_config.output_compression
        if image_config.stream and capabilities.get("stream", False):
            params["stream"] = True
            if image_config.partial_images:
                params["partial_images"] = image_config.partial_images
        return params

    def _responses_image_generation_tool(self, task: TaskPlan) -> dict[str, Any]:
        image_config = self.config.image
        capabilities = get_model_capabilities(self.config.api.model)
        tool: dict[str, Any] = {
            "type": "image_generation",
            "action": mode_to_responses_action(task.mode),
            "model": self.config.api.model,
        }
        for key, value, capability_key in [
            ("size", image_config.size, "size"),
            ("quality", image_config.quality, "qualities"),
            ("output_format", image_config.output_format, "output_formats"),
            ("background", image_config.background, "backgrounds"),
            ("moderation", image_config.moderation, "moderations"),
        ]:
            if key == "size":
                if _should_send_size(capabilities, value):
                    tool[key] = value
                continue
            if key == "quality":
                if _should_send_quality(capabilities, value):
                    tool[key] = value
                continue
            if _is_supported(capabilities, capability_key, value):
                tool[key] = value

        if image_config.output_compression is not None:
            tool["output_compression"] = image_config.output_compression
        if image_config.partial_images:
            tool["partial_images"] = image_config.partial_images
        if task.mask_path is not None:
            tool["input_image_mask"] = {"image_url": _data_url(task.mask_path)}
        return tool

    def _responses_input(self, task: TaskPlan) -> Any:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": task.rendered_prompt}]
        for source_path in task.source_paths:
            content.append({"type": "input_image", "image_url": _data_url(source_path), "detail": "auto"})
        input_items = [{"role": "user", "content": content}]
        if self.config.api.image_generation_call_id:
            input_items.append({"type": "image_generation_call", "id": self.config.api.image_generation_call_id})
        return input_items


class DeterministicMockImageClient:
    def __init__(self, *, b64_json: str | None = None) -> None:
        self.b64_json = b64_json or (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
        )

    async def run_task(self, task: TaskPlan) -> ImageClientResult:
        return [CompletedImage(b64_json=self.b64_json, usage={"mock": True})]


async def _collect_non_stream(response: Any) -> ImageClientResult:
    _raise_response_issue(response)
    usage = _as_dict(getattr(response, "usage", None))
    results: ImageClientResult = []
    for item in getattr(response, "data", []) or []:
        b64_json = _get_value(item, "b64_json")
        if b64_json:
            results.append(CompletedImage(b64_json=str(b64_json), usage=usage))
    return results


def _collect_responses_response(response: Any) -> ImageClientResult:
    _raise_response_issue(response)
    usage = _as_dict(getattr(response, "usage", None)) or {}
    response_id = _get_value(response, "id")
    if response_id:
        usage["response_id"] = response_id

    results: ImageClientResult = []
    for item in getattr(response, "output", []) or []:
        _raise_response_issue(item)
        if _get_value(item, "type") != "image_generation_call":
            continue
        b64_json = _get_value(item, "result")
        if not b64_json:
            continue
        item_usage = dict(usage)
        item_id = _get_value(item, "id")
        if item_id:
            item_usage["image_generation_call_id"] = item_id
        results.append(CompletedImage(b64_json=str(b64_json), usage=item_usage))
    return results


async def _collect_stream(response: Any) -> ImageClientResult:
    results: ImageClientResult = []
    async for event in response:
        event_type = str(_get_value(event, "type") or "")
        _raise_response_issue(event)
        b64_json = _get_value(event, "b64_json") or _get_value(event, "partial_image_b64")
        if not b64_json and event_type == "response.output_item.done":
            item = _get_value(event, "item")
            if _get_value(item, "type") == "image_generation_call":
                b64_json = _get_value(item, "result")
        if not b64_json:
            continue
        if "partial" in event_type:
            index = _get_value(event, "partial_image_index")
            if index is None:
                index = _get_value(event, "index") or len([r for r in results if isinstance(r, PartialImage)])
            results.append(PartialImage(index=int(index), b64_json=str(b64_json)))
        elif "completed" in event_type or "complete" in event_type:
            results.append(CompletedImage(b64_json=str(b64_json), usage=_as_dict(_get_value(event, "usage"))))
        elif event_type == "response.output_item.done":
            results.append(CompletedImage(b64_json=str(b64_json), usage=None))
    return results


class _ResponsePayloadError(Exception):
    def __init__(self, payload: Any) -> None:
        self.body = payload
        self.status_code = _get_value(payload, "status_code")
        message = _get_value(payload, "message") or _get_value(payload, "code") or "API response error"
        super().__init__(str(message))


def _raise_response_issue(value: Any) -> None:
    if value is None:
        return

    reason = _get_value(_get_value(value, "incomplete_details"), "reason")
    if _looks_like_content_policy(reason):
        raise ImageBatchError("content_policy", f"API response was filtered: {reason}", retryable=False)

    refusal = _find_refusal(value)
    if refusal:
        raise ImageBatchError("content_policy", str(refusal), retryable=False)

    error_payload = _get_value(value, "error")
    if error_payload:
        raise classify_exception(_ResponsePayloadError(error_payload))

    nested_response = _get_value(value, "response")
    if nested_response is not None and nested_response is not value:
        _raise_response_issue(nested_response)


def _find_refusal(value: Any) -> str | None:
    value_type = _get_value(value, "type")
    if value_type == "refusal":
        return str(_get_value(value, "refusal") or _get_value(value, "text") or "API refused the request.")

    for key in ("output", "content"):
        for item in _as_list(_get_value(value, key)):
            refusal = _find_refusal(item)
            if refusal:
                return refusal
    return None


def _looks_like_content_policy(value: Any) -> bool:
    text = str(value or "").lower()
    return any(
        token in text
        for token in [
            "content_policy",
            "content policy",
            "content_filter",
            "content filter",
            "safety",
            "moderation",
            "policy_violation",
        ]
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _get_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _as_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {"value": value}


def _data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def _is_supported(capabilities: dict[str, Any], key: str, value: str | None) -> bool:
    if value is None:
        return False
    return value in (capabilities.get(key) or [])


def _should_send_quality(capabilities: dict[str, Any], value: str) -> bool:
    return value in (capabilities.get("qualities") or [])


def _should_send_size(capabilities: dict[str, Any], value: str) -> bool:
    size_config = capabilities.get("size") or {}
    if not isinstance(size_config, dict):
        return False
    if value == "auto":
        return bool(size_config.get("auto", False))
    allowed = size_config.get("allowed") or []
    return value in allowed or "edge_multiple" in size_config


def _resolve_api_key(config: AppConfig) -> str | None:
    if config.api.api_key:
        return config.api.api_key

    source = config.api.api_key_source
    if source == "none":
        return None
    if source == "env":
        return _read_required_env("OPENAI_API_KEY")
    if source.startswith("env:"):
        return _read_required_env(source.removeprefix("env:"))
    if source in {"keyring", "windows_credential_manager"}:
        return _read_keyring_api_key(source)
    raise RuntimeError(f"Unsupported api_key_source: {source}")


def _resolve_base_url(config: AppConfig) -> str | None:
    base_url = config.api.base_url or os.environ.get("OPENAI_BASE_URL")
    if not base_url:
        return None
    return _normalize_openai_base_url(base_url)


def _normalize_openai_base_url(value: str) -> str | None:
    stripped = value.strip().rstrip("/")
    if not stripped:
        return None

    parsed = urlsplit(stripped)
    if parsed.scheme in {"http", "https"} and parsed.netloc and parsed.path in {"", "/"}:
        return urlunsplit((parsed.scheme, parsed.netloc, "/v1", "", ""))
    return stripped


def _read_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"API key not found in environment variable {name}")
    return value


def _read_keyring_api_key(source: str) -> str:
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError(
            f"api_key_source={source!r} requires the optional keyring package"
        ) from exc

    candidates = [
        ("gpt-image-batch", "OPENAI_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
    ]
    for service_name, username in candidates:
        value = keyring.get_password(service_name, username)
        if value:
            return value

    raise RuntimeError(
        "API key not found in Windows Credential Manager/keyring. "
        "Store it under service 'gpt-image-batch' and username 'OPENAI_API_KEY'."
    )


__all__ = [
    "CompletedImage",
    "DeterministicMockImageClient",
    "ImageClient",
    "ImageClientResult",
    "OpenAIImageClient",
    "PartialImage",
]
