from __future__ import annotations

import json
import threading
from urllib.request import Request, urlopen

import pytest

from voiceops.adapters.higgs_realtime import HiggsRealtimeSession
from voiceops.governed_tools import (
    execute_tool_call,
    get_operational_registry,
    inneros_analyze_incident,
    inspect_operational_state,
)
from voiceops.webapp import VoiceOpsDemoServer


def test_conversational_greeting_zero_tools() -> None:
    session = HiggsRealtimeSession()
    res = session.converse("Hola, ¿cómo estás?")
    assert "¡Hola!" in res["reply"] or "Muy bien" in res["reply"]
    assert res["subsystem"] == "general_dialogue"
    assert len(res["tool_records"]) == 0


def test_conversational_identity_reasoning() -> None:
    session = HiggsRealtimeSession()
    res = session.converse("¿Quién eres y qué estás haciendo conmigo hoy?")
    assert "VoiceOps" in res["reply"]
    assert "Guayaquil" in res["reply"]
    assert len(res["tool_records"]) == 0


def test_solar_query_inspects_home_assistant() -> None:
    session = HiggsRealtimeSession()
    res = session.converse("¿Cuánto está produciendo el solar ahora?")
    assert len(res["tool_records"]) > 0
    assert res["tool_records"][0]["tool_name"] == "inspect_operational_state"
    assert res["tool_records"][0]["arguments"]["subsystem"] == "solar_power"
    assert "529" in res["reply"] or "watts" in res["reply"]


def test_alarm_query_inspects_intelbras() -> None:
    session = HiggsRealtimeSession()
    res = session.converse("¿Cómo está la alarma?")
    assert len(res["tool_records"]) > 0
    assert res["tool_records"][0]["tool_name"] == "inspect_operational_state"
    assert res["tool_records"][0]["arguments"]["subsystem"] == "security_alarm"
    assert "DESARMADO" in res["reply"] or "10 zonas" in res["reply"] or "DISARMED" in res["reply"]


def test_complex_incident_root_cause_analysis_tool() -> None:
    session = HiggsRealtimeSession()
    res = session.converse("¿Por qué crees que ocurrió la falla de ayer en la red?")
    assert len(res["tool_records"]) > 0
    assert res["tool_records"][0]["tool_name"] == "inneros_analyze_incident"
    assert "Causa Raíz" in res["reply"] or "Root Cause" in res["reply"]
    assert "AP-SolarYard" in res["reply"] or "98.4V" in res["reply"]


def test_dynamic_zoiper_extension_registration_and_deregistration() -> None:
    reg = get_operational_registry()
    # Register 104
    added = reg.register_extension("104", label="Zoiper Mobile Softphone")
    assert added["ext"] == "104"
    assert any(e["ext"] == "104" for e in reg._registered_extensions)

    # Telephony telemetry reflects 104
    tel = inspect_operational_state("telephony")
    assert any(e["ext"] == "104" for e in tel["data"]["registered_extensions"])

    # Unregister 104
    unreg = reg.unregister_extension("104")
    assert unreg["ok"] is True
    assert not any(e["ext"] == "104" for e in reg._registered_extensions)


def test_instacloud_honestly_not_connected() -> None:
    telemetry = inspect_operational_state("instacloud")
    assert telemetry["data"]["status"] == "NOT CONNECTED"
    assert telemetry["data"]["truth"] == "NOT_CONNECTED"


def test_webapp_token_and_endpoints() -> None:
    server = VoiceOpsDemoServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        # 1. Ephemeral token
        with urlopen(base + "/api/boson/token", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ws_url"] == "/ws/higgs"
            assert data["model"] == "higgs-realtime-v1"
            assert data["sample_rate"] == 16000

        # 2. Register Zoiper via API
        req = Request(
            base + "/api/telephony/register-extension",
            data=json.dumps({"extension": "105", "label": "Field Zoiper"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert any(e["ext"] == "105" for e in data["all_extensions"])

        # 3. Unregister Zoiper via API
        req_unreg = Request(
            base + "/api/telephony/unregister-extension",
            data=json.dumps({"extension": "105"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req_unreg, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert not any(e["ext"] == "105" for e in data["all_extensions"])

        # 4. Incident analysis API
        req_an = Request(
            base + "/api/inneros/analyze",
            data=json.dumps({"query": "analiza la falla de ayer"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req_an, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["tool"] == "inneros_analyze_incident"
            assert "Causa Raíz" in data["root_cause"]
    finally:
        server.shutdown()
