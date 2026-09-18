from __future__ import annotations

import json
import threading
from urllib.request import Request, urlopen

from voiceops.webapp import VoiceOpsDemoServer


def _get_json(url: str) -> dict[str, object]:
    with urlopen(url, timeout=3) as response:  # noqa: S310 - local ephemeral test server
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=3) as response:  # noqa: S310 - local ephemeral test server
        return json.loads(response.read().decode("utf-8"))


def test_http_server_serves_ui_and_governed_api_flow() -> None:
    server = VoiceOpsDemoServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        with urlopen(base + "/", timeout=3) as response:  # noqa: S310 - local ephemeral test server
            page = response.read().decode("utf-8")
        assert "InnerOS VoiceOps" in page
        assert "NO PROD WRITES" in page

        health = _get_json(base + "/healthz")
        assert health["ok"] is True
        assert health["service"] == "inneros-voiceops-boson"
        assert health["production_writes"] is False

        initial = _get_json(base + "/api/state")
        assert initial["production_writes"] is False

        proposed = _post_json(base + "/api/intent", {"transcript": "Revisa la incidencia"})
        assert proposed["pending_approval"] is True
        assert proposed["proposal"]["action_type"] == "create_work_order"  # type: ignore[index]

        blocked = _post_json(base + "/api/approve", {"transcript": "Si crees que hace falta"})
        assert blocked["pending_approval"] is True
        assert blocked["action"] is None

        completed = _post_json(base + "/api/approve", {"transcript": "Si, autorizo"})
        assert completed["pending_approval"] is False
        assert completed["action"]["status"] == "created"  # type: ignore[index]

        replay = _get_json(base + "/api/replay")
        assert replay["replay_source"] == "captured_evidence_only"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_browser_voice_agent_uses_progressive_tools_and_spanish_stt_context() -> None:
    server = VoiceOpsDemoServer(("127.0.0.1", 0), live_voice_enabled=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        with urlopen(base + "/app.js", timeout=3) as response:  # noqa: S310 - local ephemeral test server
            script = response.read().decode("utf-8")
        assert 'tools: [inspectTool]' in script
        assert 'tools: [approveTool]' in script
        assert 'tools: []' in script
        assert 'language_codes: ["es"]' in script
        assert '"sí autorizo"' in script
        assert '"acceso norte"' in script
        assert 'execution_mode: "interactive"' in script
        assert 'handledToolCallIds: new Set()' in script
        assert 'pendingToolCalls.some((call) => call.call_id === msg.call_id)' in script
        assert 'handledToolCallIds.add(call.call_id)' in script
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_guardian_voice_http_bridge_requires_token_and_binds_event() -> None:
    from urllib.error import HTTPError

    server = VoiceOpsDemoServer(("127.0.0.1", 0), bridge_token="fixture-bridge-key")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}"
    event = {
        "event_id": "evt_http_001",
        "source_id": "camera-2",
        "event_type": "zone.person.prolonged",
        "severity": "high",
        "occurred_at": "2026-09-11T12:00:00+00:00",
        "tenant_id": "tenant-demo",
        "site_id": "site-demo",
        "zone_id": "Puerta",
        "confidence": 0.91,
    }
    try:
        health = _get_json(base + "/healthz")
        assert health["guardian_voice_bridge_enabled"] is True
        payload = {"event": event, "transcript": "Revisa esta incidencia"}
        unauthorized = Request(
            base + "/api/guardian/voice-command",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(unauthorized, timeout=3)  # noqa: S310 - local ephemeral test server
        except HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("bridge must reject requests without authorization")

        def bridge_post(transcript: str) -> dict[str, object]:
            request = Request(
                base + "/api/guardian/voice-command",
                data=json.dumps({"event": event, "transcript": transcript}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer fixture-bridge-key",
                },
                method="POST",
            )
            with urlopen(request, timeout=3) as response:  # noqa: S310 - local ephemeral test server
                return json.loads(response.read().decode("utf-8"))

        proposed = bridge_post("Revisa esta incidencia")
        assert proposed["bridge_event_id"] == "evt_http_001"
        assert proposed["pending_approval"] is True
        completed = bridge_post("Sí, autorizo")
        assert completed["action"]["details"]["source_event_id"] == "evt_http_001"  # type: ignore[index]
        assert completed["last_result"]["permit_single_use"] is True  # type: ignore[index]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_voice_status_reports_audio_source_and_provider_modes() -> None:
    server = VoiceOpsDemoServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        status = _get_json(base + "/api/voice/status")
        assert status["AUDIO_SOURCE"] in {"HIGGS", "BROWSER_TTS_FALLBACK", "NONE"}
        assert status["STT_SOURCE"] == "SESSION_NEGOTIATED"
        providers = status["providers"]
        assert providers["browser_tts"]["mode"] == "FALLBACK"
        assert providers["instacloud"]["mode"] == "NOT_CONNECTED"
        assert "boson_higgs" in providers
        assert "home_assistant" in providers
        assert "grandstream_ami" in providers
        assert "qwen_amd" in providers
        assert "insforge" in providers
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_guardian_voice_http_bridge_rejects_unauthenticated_forwarded_loopback() -> None:
    from urllib.error import HTTPError
    import pytest
    server = VoiceOpsDemoServer(('127.0.0.1',0))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = 'http://127.0.0.1:' + str(server.server_address[1])
    try:
        health = _get_json(base+'/healthz')
        assert health['guardian_voice_bridge_enabled'] is False
        assert health['guardian_voice_bridge_mode'] == 'disabled'
        with pytest.raises(HTTPError) as caught:
            urlopen(Request(base+'/api/guardian/voice-command', data=json.dumps({'event':{'event_id':'no-auth'},'transcript':'Si, autorizo'}).encode(), headers={'Content-Type':'application/json','X-Forwarded-For':'198.51.100.20'}, method='POST'), timeout=3)
        assert caught.value.code == 401
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)
