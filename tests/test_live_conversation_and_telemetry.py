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
    assert "solar" in res["reply"].lower() or "inversor" in res["reply"].lower() or "home assistant" in res["reply"].lower()


def test_alarm_query_inspects_intelbras() -> None:
    session = HiggsRealtimeSession()
    res = session.converse("¿Cómo está la alarma?")
    assert len(res["tool_records"]) > 0
    assert res["tool_records"][0]["tool_name"] == "inspect_operational_state"
    assert res["tool_records"][0]["arguments"]["subsystem"] == "security_alarm"
    assert "alarma" in res["reply"].lower() or "alarm" in res["reply"].lower() or "home assistant" in res["reply"].lower()


def test_complex_incident_root_cause_analysis_tool() -> None:
    session = HiggsRealtimeSession()
    res = session.converse("¿Por qué crees que ocurrió la falla de ayer en la red?")
    assert len(res["tool_records"]) > 0
    assert res["tool_records"][0]["tool_name"] == "inneros_analyze_incident"
    assert "Qwen" in res["reply"] or "Causa" in res["reply"] or "unreachable" in res["reply"].lower()


def test_telephony_telemetry_uses_ami_not_in_memory_demo_list() -> None:
    reg = get_operational_registry()
    reg.register_extension("104", label="Zoiper Mobile Softphone")
    tel = inspect_operational_state("telephony")
    demo_exts = [e["ext"] for e in reg._registered_extensions]
    live_exts = [e["ext"] for e in tel["data"]["registered_extensions"]]
    assert "104" in demo_exts
    assert "104" not in live_exts
    assert tel["truth"] in {"LIVE", "UNVERIFIED", "OFFLINE"}


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
        # 1. Boson token endpoint (503 when BOSON_API_KEY absent)
        try:
            with urlopen(base + "/api/boson/token", timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                assert data.get("model") == "higgs-realtime"
        except Exception as exc:
            assert "503" in str(exc) or "Service Unavailable" in str(exc)

        # 2. Incident analysis API
        req_an = Request(
            base + "/api/inneros/analyze",
            data=json.dumps({"query": "analiza la falla de ayer"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req_an, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["tool"] == "inneros_analyze_incident"
            assert data["route"]["truth"] in {"LIVE_MODEL_RESPONSE", "OFFLINE"}
    finally:
        server.shutdown()


def test_servers_query_inspects_compute_node() -> None:
    session = HiggsRealtimeSession()
    res = session.converse("¿Cómo están mis servidores y qué servicios están corriendo?")
    assert len(res["tool_records"]) > 0
    assert res["tool_records"][0]["tool_name"] == "inspect_operational_state"
    assert res["tool_records"][0]["arguments"]["subsystem"] == "servers_rack"
    assert "AG-41" in res["reply"] or "Ryzen" in res["reply"]
    assert "RAM" in res["reply"] or "servicios" in res["reply"]


def test_multilingual_french_and_german() -> None:
    session = HiggsRealtimeSession()
    # French server inquiry
    res_fr = session.converse("Bonjour, quel est l'état des serveurs ?")
    assert "AG-41" in res_fr["reply"] or "serveur" in res_fr["reply"].lower()

    # French identity inquiry
    res_fr_id = session.converse("Qui es-tu ?")
    assert "VoiceOps" in res_fr_id["reply"]

    # German server inquiry
    res_de = session.converse("Hallo, wie ist der Status der Server?")
    assert "AG-41" in res_de["reply"] or "Server" in res_de["reply"]

    # German identity inquiry
    res_de_id = session.converse("Wer bist du?")
    assert "VoiceOps" in res_de_id["reply"]
