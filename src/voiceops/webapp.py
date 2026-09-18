from __future__ import annotations

import argparse
import hmac
import json
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .adapters.local_amd import LocalAMDReasoner
from .audit import replay_summary
from .gateway import VoiceGateway
from .runtime_env import load_runtime_env

load_runtime_env()


MAX_BODY_BYTES = 16_384
MAX_TRANSCRIPT_CHARS = 1_000
DEFAULT_INTENT = (
    "Ralphi, revisa la incidencia del acceso norte y abre una orden tecnica si corresponde."
)
DEFAULT_APPROVAL = "Si, autorizo."
VOICE_AGENT_TOKEN_URL = "https://agents.assemblyai.com/v1/token"
VOICE_AGENT_TOKEN_TTL_SECONDS = 120
VOICE_AGENT_TOKEN_RATE_LIMIT_SECONDS = 5.0


def _env_truthy(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class DemoSessionStore:
    """Thread-safe in-memory state for the judge-facing demo."""

    def __init__(self, gateway_factory: Callable[[], VoiceGateway] | None = None) -> None:
        self._lock = threading.Lock()
        self._gateway_factory = gateway_factory or VoiceGateway
        self._gateway = self._gateway_factory()
        self._last_result: dict[str, object] | None = None

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self._gateway = self._gateway_factory()
            self._last_result = None
            return self._snapshot_unlocked()

    def submit_transcript(self, transcript: str) -> dict[str, Any]:
        normalized = _normalize_transcript(transcript)
        with self._lock:
            self._last_result = self._gateway.process_final_transcript(normalized)
            return self._snapshot_unlocked()

    def submit_intent(self, transcript: str) -> dict[str, Any]:
        normalized = _normalize_transcript(transcript)
        with self._lock:
            if self._gateway.pending_approval:
                raise ValueError("an approval is already pending")
            self._last_result = self._gateway.process_final_transcript(normalized)
            return self._snapshot_unlocked()

    def approve_pending(self, phrase: str) -> dict[str, Any]:
        normalized = _normalize_transcript(phrase)
        with self._lock:
            if not self._gateway.pending_approval:
                raise ValueError("no action is awaiting approval")
            self._last_result = self._gateway.process_final_transcript(normalized)
            return self._snapshot_unlocked()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_unlocked()

    def evidence(self) -> dict[str, Any]:
        with self._lock:
            return self._gateway.evidence.to_dict()

    def replay(self) -> dict[str, Any]:
        with self._lock:
            return replay_summary(self._gateway.evidence)

    def submit_guardian_voice_command(self, event: dict[str, Any], transcript: str) -> dict[str, Any]:
        """Process an authenticated WhatsApp/voice command bound to one Guardian event."""
        normalized = _normalize_transcript(transcript)
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("Guardian event_id is required")
        with self._lock:
            current = self._gateway.workflow.inspect()
            current_event_id = str(current.get("event_id") or "")
            action = self._gateway.evidence.action_result
            if action is not None:
                action_event_id = str(action.details.get("source_event_id") or "")
                if action_event_id == event_id:
                    state = self._snapshot_unlocked()
                    state["bridge_status"] = "already_completed"
                    return state
                raise ValueError("session already completed for another Guardian event")
            if self._gateway.pending_approval:
                if current_event_id != event_id:
                    raise ValueError("approval is pending for another Guardian event")
            elif current_event_id != event_id or current.get("production_event") is not True:
                self._gateway.bind_guardian_event(event)
            self._last_result = self._gateway.process_final_transcript(normalized)
            state = self._snapshot_unlocked()
            state["bridge_status"] = str(self._last_result.get("status") or "processed")
            state["bridge_surface"] = "whatsapp_voice"
            state["bridge_event_id"] = event_id
            return state

    def tool_inspect(self, intent: str) -> dict[str, Any]:
        normalized = _normalize_transcript(intent)
        duplicate = False
        try:
            state = self.submit_intent(normalized)
        except ValueError as exc:
            if str(exc) != "an approval is already pending":
                raise
            with self._lock:
                latest = self._gateway.evidence.turns[-1].transcript if self._gateway.evidence.turns else None
                if not self._gateway.pending_approval or latest != normalized or self._gateway.evidence.proposal is None:
                    raise
                state = self._snapshot_unlocked()
                duplicate = True
        return {
            "status": "already_pending" if duplicate else (
                state.get("last_result", {}).get("status") if isinstance(state.get("last_result"), dict) else None
            ),
            "requires_approval": bool(state.get("pending_approval")),
            "guardian": state.get("guardian"),
            "route": state.get("route"),
            "proposal": state.get("proposal"),
            "correlation_id": state.get("correlation_id"),
            "production_writes": False,
        }

    def tool_approve(self, authorization_phrase: str) -> dict[str, Any]:
        duplicate = False
        try:
            state = self.approve_pending(authorization_phrase)
        except ValueError as exc:
            if str(exc) != "no action is awaiting approval":
                raise
            with self._lock:
                approval = self._gateway.evidence.approval
                action = self._gateway.evidence.action_result
                if approval is None or not approval.approved or action is None:
                    raise
                state = self._snapshot_unlocked()
                duplicate = True
        return {
            "status": "already_completed" if duplicate else (
                state.get("last_result", {}).get("status") if isinstance(state.get("last_result"), dict) else None
            ),
            "approval": state.get("approval"),
            "action": state.get("action"),
            "htr": state.get("htr"),
            "correlation_id": state.get("correlation_id"),
            "production_writes": False,
        }

    def _snapshot_unlocked(self) -> dict[str, Any]:
        evidence = self._gateway.evidence
        snapshot_event = next(
            (event for event in reversed(evidence.events) if event.kind == "state_snapshot"),
            None,
        )
        route_event = next(
            (event for event in reversed(evidence.events) if event.kind == "reasoning_route"),
            None,
        )
        guardian = snapshot_event.data.get("snapshot", {}) if snapshot_event else {}
        route = route_event.data.get("route", {}) if route_event else {}
        proposal = evidence.proposal
        approval = evidence.approval
        action = evidence.action_result
        htr = evidence.htr

        return {
            "mode": "synthetic_demo",
            "reasoning_mode": _reasoning_mode(route),
            "production_writes": False,
            "session_id": evidence.session_id,
            "correlation_id": evidence.correlation_id,
            "pending_approval": self._gateway.pending_approval,
            "last_result": self._last_result,
            "transcript": evidence.turns[-1].transcript if evidence.turns else None,
            "guardian": guardian,
            "route": route,
            "proposal": {
                "action_type": proposal.action_type,
                "summary": proposal.summary,
                "requires_approval": proposal.requires_approval,
                "payload": proposal.payload,
            }
            if proposal
            else None,
            "approval": {
                "approved": approval.approved,
                "reason": approval.reason,
            }
            if approval
            else None,
            "action": {
                "action_id": action.action_id,
                "action_type": action.action_type,
                "status": action.status,
                "details": action.details,
            }
            if action
            else None,
            "htr": {
                "manual_seconds": htr.manual_seconds,
                "human_active_seconds": htr.human_active_seconds,
                "saved_seconds": htr.saved_seconds,
                "classification": htr.classification,
            }
            if htr
            else None,
            "timeline": [
                {"kind": event.kind, "at": event.at, "data": event.data}
                for event in evidence.events
            ],
        }


def _normalize_transcript(transcript: str) -> str:
    normalized = transcript.strip()
    if not normalized:
        raise ValueError("transcript must not be empty")
    if len(normalized) > MAX_TRANSCRIPT_CHARS:
        raise ValueError(f"transcript exceeds {MAX_TRANSCRIPT_CHARS} characters")
    return normalized


def _reasoning_mode(route: dict[str, Any]) -> str:
    if route.get("provider") == "local-amd-5" and route.get("truth") == "LIVE_MODEL_RESPONSE":
        return "amd5_live"
    if route.get("truth") == "SYNTHETIC":
        return "synthetic"
    return "pending"


def build_gateway_factory(reasoner_mode: str) -> Callable[[], VoiceGateway]:
    if reasoner_mode == "synthetic":
        return VoiceGateway
    if reasoner_mode == "amd5":
        return lambda: VoiceGateway(reasoner=LocalAMDReasoner())
    raise ValueError(f"unsupported reasoner mode: {reasoner_mode}")


def mint_voice_agent_token(
    api_key: str,
    *,
    expires_in_seconds: int = VOICE_AGENT_TOKEN_TTL_SECONDS,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Mint a short-lived, single-use Voice Agent browser token server-side."""
    if not api_key.strip():
        raise ValueError("AssemblyAI API key is not configured")
    if not 1 <= expires_in_seconds <= 600:
        raise ValueError("expires_in_seconds must be between 1 and 600")
    url = VOICE_AGENT_TOKEN_URL + "?" + urlencode({"expires_in_seconds": expires_in_seconds})
    request = Request(url, headers={"Authorization": f"Bearer {api_key}"}, method="GET")
    with opener(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError("AssemblyAI token response did not include a token")
    return {"token": token, "expires_in_seconds": expires_in_seconds}


class VoiceOpsHandler(BaseHTTPRequestHandler):
    server_version = "VoiceOpsDemo/0.3"

    @property
    def store(self) -> DemoSessionStore:
        return self.server.store  # type: ignore[attr-defined]

    @property
    def web_root(self) -> Path:
        return Path(__file__).with_name("web")

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._send_json(
                {
                    "ok": True,
                    "service": "inneros-voiceops",
                    "live_voice_enabled": bool(self.server.live_voice_enabled),  # type: ignore[attr-defined]
                    "credential_configured": bool(os.getenv("ASSEMBLYAI_API_KEY")),
                    "guardian_voice_bridge_enabled": bool(self.server.bridge_token) or self._loopback_bridge_allowed(),  # type: ignore[attr-defined]
                    "guardian_voice_bridge_mode": "token" if self.server.bridge_token else ("loopback_only" if self._loopback_bridge_allowed() else "disabled"),  # type: ignore[attr-defined]
                    "production_writes": False,
                }
            )
            return
        if self.path.split("?", 1)[0] == "/ws/higgs":
            self._handle_ws_higgs()
            return
        if self.path.startswith("/api/boson/token"):
            from .adapters.boson_realtime import mint_client_secret

            minted = mint_client_secret(expires_in_seconds=600)
            if not minted.get("ok"):
                self._send_json(
                    {
                        "mode": "browser_fallback",
                        "transport": "browser_stt_tts",
                        "label": "BROWSER TTS FALLBACK",
                        "ready": True,
                        "ws_url": None,
                        "sample_rate": 16000,
                        "sub_125ms_barge_in": True,
                        "provider": "Browser SpeechRecognition + speechSynthesis",
                        "reason": minted.get("error", "Boson not configured"),
                    }
                )
                return
            self._send_json(
                {
                    "mode": "higgs_relay",
                    "token": minted["client_secret"],
                    "expires_in_seconds": minted.get("expires_in_seconds", 600),
                    "ws_url": minted.get("ws_url", "/ws/higgs"),
                    "model": minted.get("model", "higgs-realtime"),
                    "voice": "default",
                    "sample_rate": 16000,
                    "bilingual_support": "English / Spanish / Spanglish Code-Switching",
                    "sub_125ms_barge_in": True,
                    "provider": "Boson AI Higgs Realtime Speech-to-Speech",
                    "ready": True,
                    "upstream": minted.get("upstream_ws_url"),
                }
            )
            return
        if self.path == "/api/integrations/status":
            from .adapters.integration_status import collect_integration_status

            self._send_json(collect_integration_status())
            return
        if self.path == "/api/telemetry":
            from .governed_tools import inspect_operational_state
            self._send_json(inspect_operational_state("all", live_fluctuation=True))
            return
        if self.path == "/api/boson/status":
            from .adapters.boson_realtime import boson_api_key

            has_key = bool(boson_api_key())
            self._send_json(
                {
                    "provider": "Boson AI Higgs Realtime S2S",
                    "model": "higgs-realtime",
                    "site": "Guayaquil Operations Hub (GYE-Node-01)",
                    "bilingual_support": "English / Spanish / Spanglish Code-Switching",
                    "sub_125ms_barge_in": True,
                    "ready": has_key,
                    "mode": "higgs_relay" if has_key else "browser_fallback",
                    "websocket_endpoint": "/ws/higgs" if has_key else None,
                    "token_endpoint": "/api/boson/token",
                }
            )
            return
        if self.path == "/api/state":
            state = self.store.snapshot()
            state["assemblyai_voice_agent_enabled"] = bool(self.server.live_voice_enabled)  # type: ignore[attr-defined]
            self._send_json(state)
            return
        if self.path == "/api/evidence":
            self._send_json(self.store.evidence())
            return
        if self.path == "/api/replay":
            self._send_json(self.store.replay())
            return
        if self.path == "/api/assemblyai/token":
            self._handle_voice_agent_token()
            return
        static_map = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "application/javascript; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
        }
        item = static_map.get(self.path)
        if item is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        filename, content_type = item
        target = self.web_root / filename
        if not target.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path == "/api/telephony/register-extension":
                from .governed_tools import get_operational_registry
                payload = self._read_json()
                ext = str(payload.get("extension") or payload.get("ext") or "").strip()
                label = str(payload.get("label") or "Zoiper SIP Softphone").strip()
                if not ext:
                    self._send_json({"error": "Extension number is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                reg = get_operational_registry()
                new_ext = reg.register_extension(ext=ext, label=label, status="ONLINE")
                self._send_json({"ok": True, "registered_extension": new_ext, "all_extensions": list(reg._registered_extensions)})
                return
            if self.path == "/api/telephony/unregister-extension":
                from .governed_tools import get_operational_registry
                payload = self._read_json()
                ext = str(payload.get("extension") or payload.get("ext") or "").strip()
                if not ext:
                    self._send_json({"error": "Extension number is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                reg = get_operational_registry()
                unreg_res = reg.unregister_extension(ext=ext)
                self._send_json(unreg_res)
                return
            if self.path == "/api/inneros/analyze":
                from .governed_tools import inneros_analyze_incident
                payload = self._read_json()
                query = str(payload.get("query") or "analiza la causa de la falla de ayer")
                sub = str(payload.get("subsystem") or "all")
                self._send_json(inneros_analyze_incident(query, sub))
                return
            if self.path == "/api/governed/inspect":
                from .governed_tools import inspect_operational_state
                payload = self._read_json()
                subsystem = str(payload.get("subsystem") or "all")
                self._send_json(inspect_operational_state(subsystem))
                return
            if self.path == "/api/governed/propose":
                from .governed_tools import propose_governed_action
                payload = self._read_json()
                action_type = str(payload.get("action_type") or "restart_wifi_ap")
                target_subsystem = str(payload.get("target_subsystem") or "network_wifi")
                params = payload.get("parameters")
                self._send_json(propose_governed_action(action_type, target_subsystem, params))
                return
            if self.path == "/api/governed/approve":
                from .governed_tools import submit_user_approval
                payload = self._read_json()
                proposal_id = str(payload.get("proposal_id") or "")
                utterance = str(payload.get("utterance") or "")
                self._send_json(submit_user_approval(proposal_id, utterance))
                return
            if self.path == "/api/governed/simulate":
                from .adapters.higgs_realtime import HiggsRealtimeSession
                payload = self._read_json()
                utterance = str(payload.get("utterance") or "Revisa el estado de la red y propone solucion")
                sim_tool = payload.get("tool_call")
                tool_tuple = (sim_tool["name"], sim_tool.get("args", {})) if sim_tool else None
                sim_interruption = bool(payload.get("interruption", False))
                session = HiggsRealtimeSession()
                sim_res = session.simulate_conversation_turn(
                    user_utterance=utterance,
                    simulate_tool_call=tool_tuple,
                    simulate_interruption=sim_interruption,
                )
                self._send_json(sim_res)
                return
            if self.path == "/api/boson/converse":
                from .adapters.higgs_realtime import HiggsRealtimeSession
                payload = self._read_json()
                utterance = str(payload.get("utterance") or "")
                active_prop = payload.get("active_proposal_id")
                session = HiggsRealtimeSession()
                conv_res = session.converse(user_utterance=utterance, active_proposal_id=active_prop)
                self._send_json(conv_res)
                return
            if self.path == "/api/reset":
                self._send_json(self.store.reset())
                return
            if self.path == "/api/intent":
                payload = self._read_json()
                self._send_json(self.store.submit_intent(str(payload.get("transcript") or DEFAULT_INTENT)))
                return
            if self.path == "/api/approve":
                payload = self._read_json()
                self._send_json(self.store.approve_pending(str(payload.get("transcript") or DEFAULT_APPROVAL)))
                return
            if self.path == "/api/tool/inspect-and-propose":
                payload = self._read_json()
                self._send_json(self.store.tool_inspect(str(payload.get("intent") or DEFAULT_INTENT)))
                return
            if self.path == "/api/tool/approve-pending":
                payload = self._read_json()
                self._send_json(self.store.tool_approve(str(payload.get("authorization_phrase") or "")))
                return
            if self.path == "/api/guardian/voice-command":
                payload = self._read_json()
                if not self._bridge_authorized():
                    self._send_json({"error": "guardian voice bridge unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
                    return
                event = payload.get("event")
                if not isinstance(event, dict):
                    raise ValueError("event must be a Guardian NormalizedEvent object")
                self._send_json(
                    self.store.submit_guardian_voice_command(
                        event,
                        str(payload.get("transcript") or ""),
                    )
                )
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except (OSError, TimeoutError) as exc:
            self._send_json(
                {"error": f"provider unavailable: {type(exc).__name__}"},
                status=HTTPStatus.BAD_GATEWAY,
            )

    def _loopback_bridge_allowed(self) -> bool:
        server_host = str(self.server.server_address[0] or "")
        client_host = str(self.client_address[0] or "")
        return server_host in {"127.0.0.1", "::1", "localhost"} and client_host in {"127.0.0.1", "::1"}

    def _bridge_authorized(self) -> bool:
        expected = str(self.server.bridge_token or "")  # type: ignore[attr-defined]
        if expected:
            raw = self.headers.get("Authorization", "")
            prefix = "Bearer "
            return raw.startswith(prefix) and hmac.compare_digest(raw[len(prefix):].strip(), expected)
        return self._loopback_bridge_allowed()

    def _handle_voice_agent_token(self) -> None:
        if not bool(self.server.live_voice_enabled):  # type: ignore[attr-defined]
            self._send_json(
                {"error": "live AssemblyAI Voice Agent mode is disabled"},
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        api_key = os.getenv("ASSEMBLYAI_API_KEY", "")
        if not api_key:
            self._send_json(
                {"error": "AssemblyAI server credential is not configured"},
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        now = time.monotonic()
        last = float(self.server.last_token_issued_at)  # type: ignore[attr-defined]
        if now - last < VOICE_AGENT_TOKEN_RATE_LIMIT_SECONDS:
            self._send_json({"error": "voice token rate limit"}, status=HTTPStatus.TOO_MANY_REQUESTS)
            return
        token_payload = mint_voice_agent_token(api_key)
        self.server.last_token_issued_at = now  # type: ignore[attr-defined]
        self._send_json(token_payload)

    def _handle_ws_higgs(self) -> None:
        """RFC 6455 WebSocket relay to Boson Higgs Realtime upstream."""
        from urllib.parse import parse_qs, urlparse

        from .adapters.boson_realtime import relay_browser_websocket
        from .websocket_server import compute_accept_key, encode_ws_frame, read_ws_frame

        sec_key = self.headers.get("Sec-WebSocket-Key", "")
        if not sec_key:
            self.send_error(HTTPStatus.BAD_REQUEST, "Missing Sec-WebSocket-Key")
            return

        parsed = urlparse(self.path)
        client_secret = parse_qs(parsed.query).get("token", [""])[0].strip()
        if not client_secret:
            self.send_error(HTTPStatus.UNAUTHORIZED, "Missing Boson client secret token")
            return

        accept_val = compute_accept_key(sec_key)
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept_val)
        self.end_headers()

        def read_frame() -> tuple[int, bytes] | None:
            return read_ws_frame(self.rfile)

        def write_frame(opcode: int, payload: bytes) -> None:
            self.wfile.write(encode_ws_frame(opcode, payload))
            self.wfile.flush()

        try:
            relay_browser_websocket(
                read_frame=read_frame,
                write_frame=write_frame,
                client_secret=client_secret,
            )
        except Exception as exc:
            err = json.dumps(
                {
                    "type": "error",
                    "mode": "browser_fallback",
                    "label": "BROWSER TTS FALLBACK",
                    "message": str(exc),
                }
            ).encode("utf-8")
            try:
                write_frame(1, err)
                write_frame(8, b"")
            except Exception:
                pass

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="replace")
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _send_json(self, payload: Any, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


class VoiceOpsDemoServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        gateway_factory: Callable[[], VoiceGateway] | None = None,
        live_voice_enabled: bool = False,
        bridge_token: str = "",
    ) -> None:
        super().__init__(server_address, VoiceOpsHandler)
        self.store = DemoSessionStore(gateway_factory=gateway_factory)
        self.live_voice_enabled = live_voice_enabled
        self.bridge_token = bridge_token
        self.last_token_issued_at = 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="InnerOS VoiceOps judge demo web UI")
    parser.add_argument("--host", default=os.getenv("VOICEOPS_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", os.getenv("VOICEOPS_PORT", "8765"))),
    )
    parser.add_argument(
        "--reasoner",
        choices=("synthetic", "amd5"),
        default=os.getenv("VOICEOPS_REASONER", "synthetic"),
        help="Use offline-safe synthetic reasoning or the existing local AMD .5 runtime.",
    )
    parser.add_argument(
        "--enable-live-assemblyai",
        action="store_true",
        default=_env_truthy("VOICEOPS_ENABLE_LIVE_ASSEMBLYAI"),
        help="Enable short-lived browser Voice Agent tokens. Requires ASSEMBLYAI_API_KEY server-side.",
    )
    args = parser.parse_args()
    load_runtime_env()
    server = VoiceOpsDemoServer(
        (args.host, args.port),
        gateway_factory=build_gateway_factory(args.reasoner),
        live_voice_enabled=args.enable_live_assemblyai,
        bridge_token=os.getenv("VOICEOPS_BRIDGE_TOKEN", ""),
    )
    print(
        f"InnerOS VoiceOps demo: http://{args.host}:{args.port} · reasoner={args.reasoner} "
        f"· live_assemblyai={args.enable_live_assemblyai}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
