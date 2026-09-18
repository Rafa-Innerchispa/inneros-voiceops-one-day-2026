from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..governed_tools import HIGGS_TOOL_DEFINITIONS, execute_tool_call

logger = logging.getLogger("voiceops.boson_realtime")

BOSON_CLIENT_SECRETS_URL = "https://api.boson.ai/v1/realtime/client_secrets"
BOSON_REALTIME_WS_URL = "wss://api.boson.ai/v1/realtime"
BOSON_MODEL = "higgs-realtime"


def boson_api_key() -> str:
    return (os.getenv("BOSON_API_KEY") or os.getenv("HIGGS_API_KEY") or "").strip()


def mint_client_secret(
    *,
    api_key: str | None = None,
    expires_in_seconds: int = 600,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Mint an ephemeral Boson Realtime client secret (server-side only)."""
    key = (api_key or boson_api_key()).strip()
    if not key:
        return {"ok": False, "error": "BOSON_API_KEY not configured", "mode": "browser_fallback"}

    body = json.dumps(
        {
            "expires_in": max(10, min(expires_in_seconds, 7200)),
            "session": {
                "model": BOSON_MODEL,
                "modalities": ["audio"],
                "instructions": (
                    "You are InnerOS VoiceOps for Guayaquil infrastructure. "
                    "Converse naturally in Spanish or English. Use provided tools only for operational queries or governed actions."
                ),
                "tools": HIGGS_TOOL_DEFINITIONS,
                "tool_choice": "auto",
                "voice": "default",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
            },
        }
    ).encode("utf-8")
    request = Request(
        BOSON_CLIENT_SECRETS_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        logger.warning("Boson client_secrets HTTP error: %s %s", exc.code, detail)
        return {"ok": False, "error": f"Boson client_secrets HTTP {exc.code}", "mode": "browser_fallback"}
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Boson client_secrets failed: %s", exc)
        return {"ok": False, "error": str(exc), "mode": "browser_fallback"}

    secret = _extract_client_secret(payload)
    if not secret:
        return {"ok": False, "error": "client_secret missing in Boson response", "mode": "browser_fallback"}

    return {
        "ok": True,
        "mode": "higgs_relay",
        "client_secret": secret,
        "expires_in_seconds": expires_in_seconds,
        "model": BOSON_MODEL,
        "ws_url": "/ws/higgs",
        "upstream_ws_url": BOSON_REALTIME_WS_URL,
    }


def _extract_client_secret(payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("value", "client_secret", "secret"):
        direct = payload.get(key)
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
    nested = payload.get("client_secret")
    if isinstance(nested, dict):
        value = nested.get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def relay_browser_websocket(
    *,
    read_frame: Callable[[], tuple[int, bytes] | None],
    write_frame: Callable[[int, bytes], None],
    client_secret: str,
    on_tool_event: Callable[[str, dict[str, Any], dict[str, Any]], None] | None = None,
) -> None:
    """Bidirectional relay between browser WS and Boson Realtime upstream."""
    try:
        import websocket  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("websocket-client package required for Boson relay") from exc

    upstream = websocket.create_connection(
        BOSON_REALTIME_WS_URL,
        header=[f"Authorization: Bearer {client_secret}"],
        timeout=30,
    )
    stop = threading.Event()

    def upstream_reader() -> None:
        try:
            while not stop.is_set():
                raw = upstream.recv()
                if raw is None:
                    break
                if isinstance(raw, bytes):
                    text = raw.decode("utf-8", errors="replace")
                else:
                    text = str(raw)
                try:
                    event = json.loads(text)
                except json.JSONDecodeError:
                    write_frame(1, text.encode("utf-8"))
                    continue

                handled = _maybe_handle_tool_call(event, upstream, on_tool_event)
                if handled:
                    continue
                write_frame(1, json.dumps(event, ensure_ascii=False).encode("utf-8"))
        except Exception as exc:
            logger.info("Boson upstream reader ended: %s", exc)
        finally:
            stop.set()

    reader = threading.Thread(target=upstream_reader, daemon=True)
    reader.start()

    try:
        while not stop.is_set():
            frame = read_frame()
            if frame is None:
                break
            opcode, payload = frame
            if opcode == 8:
                write_frame(8, payload)
                break
            if opcode == 9:
                write_frame(10, payload)
                continue
            if opcode != 1:
                continue
            try:
                msg = json.loads(payload.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            msg_type = msg.get("type", "")
            if msg_type == "input_audio_buffer.speech_started":
                upstream.send(json.dumps({"type": "response.cancel"}))
                upstream.send(json.dumps(msg, ensure_ascii=False))
            elif msg_type == "input_audio_buffer.append":
                audio_b64 = msg.get("audio") or msg.get("delta") or ""
                upstream.send(json.dumps({"type": "input_audio_buffer.append", "audio": audio_b64}))
            elif msg_type in {"conversation.item.create", "response.create", "session.update"}:
                upstream.send(json.dumps(msg, ensure_ascii=False))
            elif msg_type == "input_audio_buffer.commit":
                upstream.send(json.dumps(msg, ensure_ascii=False))
            else:
                upstream.send(json.dumps(msg, ensure_ascii=False))
    finally:
        stop.set()
        try:
            upstream.close()
        except Exception:
            pass
        reader.join(timeout=2.0)


def _maybe_handle_tool_call(
    event: dict[str, Any],
    upstream: Any,
    on_tool_event: Callable[[str, dict[str, Any], dict[str, Any]], None] | None,
) -> bool:
    event_type = event.get("type", "")
    if event_type not in {
        "response.function_call_arguments.done",
        "response.output_item.done",
    }:
        return False

    name = event.get("name") or (event.get("item") or {}).get("name")
    if not name:
        return False

    args_raw = event.get("arguments") or (event.get("item") or {}).get("arguments") or "{}"
    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
    except Exception:
        args = {}

    call_id = event.get("call_id") or (event.get("item") or {}).get("call_id") or f"call_{int(time.time())}"
    output = execute_tool_call(str(name), args if isinstance(args, dict) else {})
    if on_tool_event:
        on_tool_event(str(name), args if isinstance(args, dict) else {}, output)

    upstream.send(
        json.dumps(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(output, ensure_ascii=False),
                },
            },
            ensure_ascii=False,
        )
    )
    upstream.send(json.dumps({"type": "response.create"}))
    return True
