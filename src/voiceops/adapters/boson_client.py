from __future__ import annotations

import json
import logging
import os
import ssl
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..governed_tools import HIGGS_TOOL_DEFINITIONS, execute_tool_call

logger = logging.getLogger("voiceops.boson_client")

BOSON_API_BASE = "https://api.boson.ai/v1"
BOSON_REALTIME_WS = "wss://api.boson.ai/v1/realtime"
DEFAULT_MODEL = "higgs-realtime"
DEFAULT_INSTRUCTIONS = (
    "You are InnerOS VoiceOps for Guayaquil Operations (Ecuador). "
    "Speak naturally in Spanish or English. Keep replies concise (1-3 sentences). "
    "Use tools for live telemetry and governed actions; never invent approvals."
)


def get_boson_api_key() -> str:
    return (os.environ.get("BOSON_API_KEY") or os.environ.get("HIGGS_API_KEY") or "").strip()


def boson_configured() -> bool:
    return bool(get_boson_api_key())


def mint_client_secret(*, ttl_seconds: int = 600) -> dict[str, Any]:
    """Mint a short-lived Boson ephemeral key for browser-side Realtime connections."""
    api_key = get_boson_api_key()
    if not api_key:
        return {
            "ok": False,
            "error": "BOSON_API_KEY not configured",
            "status": "NOT_CONNECTED",
        }

    body = json.dumps({"expires_after": {"seconds": max(10, min(ttl_seconds, 7200))}}).encode("utf-8")
    req = Request(
        f"{BOSON_API_BASE}/realtime/client_secrets",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        logger.warning("Boson client_secrets HTTP %s: %s", exc.code, detail)
        return {"ok": False, "error": f"client_secrets HTTP {exc.code}", "detail": detail}
    except URLError as exc:
        logger.warning("Boson client_secrets unreachable: %s", exc)
        return {"ok": False, "error": str(exc), "status": "UNREACHABLE"}

    secret_value = payload.get("value") or payload.get("client_secret", {}).get("value")
    if not secret_value:
        return {"ok": False, "error": "client_secrets response missing value", "raw": payload}

    expires_at = payload.get("expires_at")
    expires_in = 600
    if isinstance(expires_at, (int, float)):
        expires_in = max(0, int(expires_at - time.time()))

    return {
        "ok": True,
        "token": secret_value,
        "expires_in_seconds": expires_in,
        "ws_url": f"{BOSON_REALTIME_WS}?model={DEFAULT_MODEL}",
        "model": DEFAULT_MODEL,
        "connection_mode": "direct",
        "subprotocol_prefix": "bai-client-secret.",
        "provider": "Boson AI Higgs Realtime",
        "ready": True,
        "AUDIO_SOURCE": "HIGGS",
        "sample_rate": 24000,
    }


def build_session_update(*, instructions: str | None = None) -> dict[str, Any]:
    """Build Boson-compatible session.update with VoiceOps governed tools."""
    openai_tools = []
    for tool in HIGGS_TOOL_DEFINITIONS:
        openai_tools.append(
            {
                "type": "function",
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
            }
        )

    return {
        "type": "session.update",
        "session": {
            "model": DEFAULT_MODEL,
            "instructions": instructions or DEFAULT_INSTRUCTIONS,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "turn_detection": {"type": "server_vad"},
                    "transcription": {"model": "higgs-stt-3.1", "language": "es"},
                },
                "output": {"voice": "default"},
            },
            "tools": openai_tools,
            "tool_choice": "auto",
            "temperature": 0.6,
        },
    }


def handle_tool_call_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Execute a VoiceOps tool locally and return outbound Realtime events."""
    if event.get("type") != "response.function_call_arguments.done":
        return None

    call_id = event.get("call_id") or event.get("id") or f"call_{int(time.time())}"
    name = event.get("name", "")
    args_raw = event.get("arguments", "{}")
    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw or {})
    except json.JSONDecodeError:
        args = {}

    output = execute_tool_call(name, args)
    return {
        "tool_output_event": {
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(output, ensure_ascii=False),
            },
        },
        "response_create_event": {"type": "response.create"},
        "record": {"tool_name": name, "arguments": args, "output": output},
    }


def relay_boson_websocket(
    browser_send: Callable[[bytes], None],
    browser_recv: Callable[[], bytes | None],
    *,
    use_ephemeral: str | None = None,
) -> None:
    """Bidirectional relay between browser RFC6455 socket and Boson Realtime upstream."""
    try:
        import websocket  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("websocket-client package required for Boson relay") from exc

    api_key = get_boson_api_key()
    if not api_key and not use_ephemeral:
        raise RuntimeError("BOSON_API_KEY not configured for relay")

    url = f"{BOSON_REALTIME_WS}?model={DEFAULT_MODEL}"
    headers: list[str] = []
    subprotocols: list[str] = ["realtime"]
    if use_ephemeral:
        subprotocols.append(f"bai-client-secret.{use_ephemeral}")
    else:
        headers.append(f"Authorization: Bearer {api_key}")

    upstream = websocket.create_connection(
        url,
        header=headers,
        subprotocols=subprotocols,
        sslopt={"cert_reqs": ssl.CERT_REQUIRED},
        timeout=30,
    )
    selected = upstream.subprotocol or ""
    logger.info("Boson upstream connected (subprotocol=%s)", selected)

    session_sent = threading.Event()
    stop = threading.Event()

    def upstream_reader() -> None:
        try:
            while not stop.is_set():
                raw = upstream.recv()
                if raw is None:
                    break
                if isinstance(raw, bytes):
                    text = raw.decode("utf-8")
                else:
                    text = str(raw)
                try:
                    event = json.loads(text)
                except json.JSONDecodeError:
                    browser_send(raw if isinstance(raw, bytes) else text.encode("utf-8"))
                    continue

                evt_type = event.get("type", "")
                if evt_type == "session.created" and not session_sent.is_set():
                    upstream.send(json.dumps(build_session_update()))
                    session_sent.set()

                tool_followup = handle_tool_call_event(event)
                browser_send(text.encode("utf-8"))
                if tool_followup:
                    upstream.send(json.dumps(tool_followup["tool_output_event"]))
                    upstream.send(json.dumps(tool_followup["response_create_event"]))
        except Exception as exc:
            logger.warning("Boson upstream reader stopped: %s", exc)
        finally:
            stop.set()

    reader = threading.Thread(target=upstream_reader, daemon=True)
    reader.start()

    try:
        while not stop.is_set():
            payload = browser_recv()
            if payload is None:
                break
            text = payload.decode("utf-8")
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                upstream.send(text)
                continue

            msg_type = msg.get("type", "")
            if msg_type == "response.cancel":
                upstream.send(json.dumps({"type": "response.cancel"}))
                continue
            upstream.send(text)
    finally:
        stop.set()
        try:
            upstream.close()
        except Exception:
            pass
        reader.join(timeout=2.0)
