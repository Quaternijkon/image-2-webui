from __future__ import annotations

import socket

from app.webui.gradio_app import build_demo


def launch_webui(
    *,
    host: str = "127.0.0.1",
    port: int = 7860,
    share: bool = False,
    auth: str | None = None,
    auto_launch: bool = True,
) -> None:
    demo = build_demo()
    auth_tuple = _parse_auth(auth)
    launch_port = resolve_launch_port(host, port)
    if launch_port != port:
        print(f"Port {port} is in use; launching WebUI on port {launch_port} instead.")
    demo.queue().launch(
        server_name=host,
        server_port=launch_port,
        share=share,
        auth=auth_tuple,
        inbrowser=auto_launch,
    )


def resolve_launch_port(host: str, preferred_port: int, *, max_attempts: int = 100) -> int:
    for candidate in range(preferred_port, min(65535, preferred_port + max_attempts - 1) + 1):
        if _is_port_available(host, candidate):
            return candidate
    raise RuntimeError(
        f"Cannot find an empty port in range {preferred_port}-{preferred_port + max_attempts - 1}."
    )


def _parse_auth(auth: str | None) -> tuple[str, str] | None:
    if not auth:
        return None
    if ":" not in auth:
        raise ValueError("auth must be USER:PASSWORD")
    username, password = auth.split(":", 1)
    if not username or not password:
        raise ValueError("auth must be USER:PASSWORD")
    return username, password


def _is_port_available(host: str, port: int) -> bool:
    bind_host = "127.0.0.1" if host in {"0.0.0.0", "localhost"} else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((bind_host, port))
        except OSError:
            return False
    return True


__all__ = ["launch_webui", "resolve_launch_port"]
