from __future__ import annotations

import asyncio
import json
import pytest

from voiceops.adapters.higgs_realtime import (
    HiggsRealtimeConfig,
    HiggsRealtimeSession,
)
from voiceops.governed_tools import (
    HIGGS_TOOL_DEFINITIONS,
    execute_tool_call,
    inspect_operational_state,
    propose_governed_action,
    submit_user_approval,
)


def test_inspect_operational_state_all() -> None:
    telemetry = inspect_operational_state("all")
    assert telemetry["site"] == "Guayaquil Operations Hub (GYE-Node-01)"
    assert telemetry["country"] == "Ecuador (EC)"
    assert "subsystems" in telemetry
    subsystems = telemetry["subsystems"]
    assert "telephony" in subsystems
    assert "solar_power" in subsystems
    assert "network_wifi" in subsystems
    assert "dmx_lighting" in subsystems
    assert "servers_rack" in subsystems


def test_inspect_individual_subsystems() -> None:
    # Telephony
    tel = inspect_operational_state("telephony")
    assert tel["data"]["hardware"] == "Grandstream UCM6104 (Firmware 1.0.20.48)"
    assert len(tel["data"]["registered_extensions"]) >= 4

    # Solar
    sol = inspect_operational_state("solar_power")
    assert sol["data"]["solar_generation_watts"] == 529
    assert sol["data"]["battery_charge_pct"] == 100.0

    # Security Alarm (Intelbras)
    alm = inspect_operational_state("security_alarm")
    assert alm["data"]["partition"] == "Panel Home Ralphi (Partition 0)"
    assert alm["data"]["monitored_zones_count"] == 10

    # Video Surveillance (Dahua)
    cam = inspect_operational_state("video_surveillance")
    assert "192.168.1.100" in cam["data"]["nvr_host"]

    # Network
    net = inspect_operational_state("network_wifi")
    assert "AP-SolarYard" in [ap["ap_id"] for ap in net["data"]["access_points"]]

    # DMX
    dmx = inspect_operational_state("dmx_lighting")
    assert dmx["data"]["protocol"] == "Art-Net / DMX-512 over RS-485 (Universe 1)"

    # Rack
    rack = inspect_operational_state("servers_rack")
    assert rack["data"]["compute_host"] == "AMD Radeon AI PRO R9700 Edge Accelerator"


def test_governed_action_golden_path_approval_spanish() -> None:
    # 1. Propose action
    prop = propose_governed_action(
        action_type="restart_wifi_ap",
        target_subsystem="network_wifi",
        parameters={"ap_id": "AP-SolarYard"},
    )
    proposal_id = prop["proposal_id"]
    assert proposal_id.startswith("prop_")
    assert prop["requires_approval"] is True

    # 2. Submit explicit Spanish approval
    result = submit_user_approval(
        proposal_id=proposal_id,
        utterance="Si, autorizo reiniciar el punto de acceso ahora mismo.",
    )
    assert result["status"] == "EXECUTED"
    assert result["action_type"] == "restart_wifi_ap"
    assert result["permit_id"].startswith("vxp_")
    assert "evidence_sha256" in result
    assert result["htr_seconds_returned"] > 0
    assert result["details"]["execution_status"] == "SUCCESS_DEMO_SAFE"


def test_governed_action_golden_path_approval_english() -> None:
    # 1. Propose action
    prop = propose_governed_action(
        action_type="switch_solar_bypass",
        target_subsystem="solar_power",
    )
    proposal_id = prop["proposal_id"]

    # 2. Submit explicit English approval
    result = submit_user_approval(
        proposal_id=proposal_id,
        utterance="Yes, proceed and authorize solar bypass immediately.",
    )
    assert result["status"] == "EXECUTED"
    assert result["action_type"] == "switch_solar_bypass"
    assert result["details"]["htr_metric"]["saved_seconds"] == 2400.0 - 4.5


def test_governed_action_fail_closed_on_ambiguity() -> None:
    # 1. Propose action
    prop = propose_governed_action(
        action_type="isolate_solar_phase",
        target_subsystem="solar_power",
    )
    proposal_id = prop["proposal_id"]

    # 2. Submit ambiguous phrase
    result = submit_user_approval(
        proposal_id=proposal_id,
        utterance="Mmm maybe we should wait a bit, I am not totally sure.",
    )
    assert result["status"] == "BLOCKED"
    assert result["fail_closed"] is True
    assert result["decision"] == "REJECTED_OR_AMBIGUOUS"


def test_governed_action_fail_closed_on_explicit_negation() -> None:
    # 1. Propose action
    prop = propose_governed_action(
        action_type="reset_sip_trunk",
        target_subsystem="telephony",
    )
    proposal_id = prop["proposal_id"]

    # 2. Submit explicit rejection
    result = submit_user_approval(
        proposal_id=proposal_id,
        utterance="No, cancela la accion, no reiniciar la troncal.",
    )
    assert result["status"] == "BLOCKED"
    assert result["fail_closed"] is True
    assert result["reason"] == "explicit_denial_or_negation"


def test_tool_dispatch_router() -> None:
    assert len(HIGGS_TOOL_DEFINITIONS) >= 3
    tool_names = [t["name"] for t in HIGGS_TOOL_DEFINITIONS]
    assert "inspect_operational_state" in tool_names
    assert "propose_governed_action" in tool_names
    assert "submit_user_approval" in tool_names
    assert "inneros_analyze_incident" in tool_names

    out = execute_tool_call("inspect_operational_state", {"subsystem": "solar_power"})
    assert out["subsystem"] == "solar_power"


@pytest.mark.asyncio
async def test_higgs_realtime_session_events() -> None:
    barge_in_fired = False
    tool_fired = False

    async def on_barge_in() -> None:
        nonlocal barge_in_fired
        barge_in_fired = True

    async def on_tool_event(name: str, args: dict, output: dict) -> None:
        nonlocal tool_fired
        tool_fired = True

    session = HiggsRealtimeSession(
        on_barge_in=on_barge_in,
        on_tool_event=on_tool_event,
    )

    # 1. Test Session Update Config
    msg = session.get_session_update_message()
    assert msg["type"] == "session.update"
    assert len(msg["session"]["tools"]) >= 3
    assert msg["session"]["input_audio_format"] == "pcm16"

    # 2. Test Interruption / Barge-In event
    res = await session.handle_server_event({"type": "input_audio_buffer.speech_started"})
    assert res is not None
    assert res["action"] == "barge_in_triggered"
    assert barge_in_fired is True

    # 3. Test Mid-conversation Tool Call event
    prop_res = propose_governed_action("restart_wifi_ap", "network_wifi")
    pid = prop_res["proposal_id"]

    tool_event = {
        "type": "response.function_call_arguments.done",
        "call_id": "call_test_123",
        "name": "submit_user_approval",
        "arguments": json.dumps({"proposal_id": pid, "utterance": "Si, autorizo."}),
    }
    tool_res = await session.handle_server_event(tool_event)
    assert tool_res is not None
    assert tool_res["action"] == "function_executed"
    assert tool_fired is True
    assert tool_res["record"]["output"]["status"] == "EXECUTED"


def test_higgs_converse_dynamic_queries() -> None:
    session = HiggsRealtimeSession()

    # 1. Ask about alarm in Spanish
    res_alm = session.converse("¿Cómo está la alarma y qué zonas están monitoreadas?")
    assert res_alm["subsystem"] == "security_alarm"
    assert "Panel Home Ralphi" in res_alm["reply"]
    assert "10" in res_alm["reply"]

    # 2. Ask about cameras in English
    res_cam = session.converse("Show me the Dahua cameras and video surveillance status")
    assert res_cam["subsystem"] == "video_surveillance"
    assert "192.168.1.100" in res_cam["reply"]
    assert "30 FPS" in res_cam["reply"]

    # 3. Ask about solar in Spanish
    res_sol = session.converse("¿Cuánto está generando el inversor solar y qué voltaje hay?")
    assert res_sol["subsystem"] == "solar_power"
    assert "529" in res_sol["reply"]
    assert "120.6" in res_sol["reply"]

    # 4. Action proposal and approval flow
    res_prop = session.converse("Reinicia el punto de acceso AP-SolarYard")
    assert res_prop["subsystem"] == "network_wifi"
    assert "proposal" in res_prop
    pid = res_prop["proposal"]["proposal_id"]

    res_app = session.converse("Sí, autorizo la operación", active_proposal_id=pid)
    assert res_app["subsystem"] == "governance"
    assert "autorizada y ejecutada" in res_app["reply"]
