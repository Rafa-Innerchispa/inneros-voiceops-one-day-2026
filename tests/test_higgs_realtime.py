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
    for subsystem in ('telephony','solar_power','security_alarm','video_surveillance','network_wifi','dmx_lighting','servers_rack'):
        result = inspect_operational_state(subsystem)
        assert result['subsystem'] == subsystem
        assert result['truth'] in {'LIVE','UNVERIFIED','OFFLINE','STALE'}
        assert 'data' in result
        if result['truth'] == 'LIVE':
            assert result['observed_at'] and result['source_provider']
    camera = inspect_operational_state('video_surveillance')['data']
    assert camera['stream_status'] == 'UNVERIFIED'
    assert camera['motion_status'] == 'UNVERIFIED'




def test_governed_action_golden_path_approval_spanish(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('VOICEOPS_STATE_DIR', str(tmp_path))
    proposal = propose_governed_action('create_incident_ticket','solar_power')
    result = submit_user_approval(proposal['proposal_id'], 'Si, autorizo crear el ticket local.')
    assert result['status'] == 'EXECUTED'
    assert result['action_type'] == 'create_incident_ticket'
    assert result['postcondition_verified'] is True
    assert result['details']['physical_mutation'] is False
    assert result['htr_seconds_returned'] == 0
    assert len(list(tmp_path.glob('vo-*.json'))) == 1
    replay = submit_user_approval(proposal['proposal_id'], 'Si, autorizo crear el ticket local.')
    assert replay['status'] == 'BLOCKED'
    assert len(list(tmp_path.glob('vo-*.json'))) == 1




def test_governed_action_golden_path_approval_english() -> None:
    proposal = propose_governed_action('switch_solar_bypass','solar_power')
    result = submit_user_approval(proposal['proposal_id'], 'Yes, proceed and authorize solar bypass immediately.')
    assert result['status'] == 'BLOCKED'
    assert result['fail_closed'] is True
    assert 'Physical mutations disabled' in result['reason']




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


def test_higgs_realtime_session_events() -> None:
    import asyncio

    async def _run() -> None:
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

        msg = session.get_session_update_message()
        assert msg["type"] == "session.update"
        assert len(msg["session"]["tools"]) >= 3
        assert msg["session"]["input_audio_format"] == "pcm16"

        res = await session.handle_server_event({"type": "input_audio_buffer.speech_started"})
        assert res is not None
        assert res["action"] == "barge_in_triggered"
        assert barge_in_fired is True

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
        assert tool_res["record"]["output"]["status"] == "BLOCKED"

    asyncio.run(_run())


def test_higgs_converse_dynamic_queries() -> None:
    session = HiggsRealtimeSession()

    # 1. Ask about alarm in Spanish
    res_alm = session.converse("¿Cómo está la alarma y qué zonas están monitoreadas?")
    assert res_alm["subsystem"] == "security_alarm"
    assert res_alm["subsystem"] == "security_alarm"
    assert "alarma" in res_alm["reply"].lower() or "alarm" in res_alm["reply"].lower()

    # 2. Ask about cameras in English
    res_cam = session.converse("Show me the Dahua cameras and video surveillance status")
    assert res_cam["subsystem"] == "video_surveillance"
    assert "dahua" in res_cam["reply"].lower() or "video" in res_cam["reply"].lower() or "nvr" in res_cam["reply"].lower()

    # 3. Ask about solar in Spanish
    res_sol = session.converse("¿Cuánto está generando el inversor solar y qué voltaje hay?")
    assert res_sol["subsystem"] == "solar_power"
    assert "solar" in res_sol["reply"].lower() or "inversor" in res_sol["reply"].lower()

    # 4. Action proposal and approval flow
    res_prop = session.converse("Reinicia el punto de acceso AP-SolarYard")
    assert res_prop["subsystem"] == "network_wifi"
    assert "proposal" in res_prop
    pid = res_prop["proposal"]["proposal_id"]

    res_app = session.converse("Sí, autorizo la operación", active_proposal_id=pid)
    assert res_app["subsystem"] == "governance"
    assert res_app["approval_result"]["status"] == "BLOCKED"
