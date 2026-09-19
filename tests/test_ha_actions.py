from __future__ import annotations

import json
from unittest.mock import MagicMock

from voiceops.adapters.ha_actions import (
    call_ha_service,
    execute_ha_action,
    list_available_controls,
    resolve_action_spec,
)
from voiceops.governed_tools import list_home_assistant_controls, propose_governed_action, submit_user_approval
from voiceops.operational_state import OperationalStateRegistry


def test_resolve_catalog_action_for_legacy_restart_wifi_ap(monkeypatch) -> None:
    spec, error = resolve_action_spec("restart_wifi_ap", {})
    assert error is None
    assert spec is not None
    assert spec.catalog_id == "restart_wifi_ap_solaryard"
    assert spec.domain == "button"
    assert spec.service == "press"


def test_resolve_ha_service_from_entity_and_verb(monkeypatch) -> None:
    monkeypatch.setenv("VOICEOPS_HA_ALLOW_DISCOVERED", "true")
    spec, error = resolve_action_spec(
        "ha_service",
        {
            "entity_id": "light.patio",
            "verb": "off",
            "target_subsystem": "security_alarm",
        },
    )
    assert error is None
    assert spec is not None
    assert spec.domain == "light"
    assert spec.service == "turn_off"
    assert spec.entity_id == "light.patio"


def test_call_ha_service_without_token() -> None:
    result = call_ha_service("light", "turn_on", {"entity_id": "light.kitchen"})
    assert result["ok"] is False
    assert "HASS_TOKEN" in result["error"]


def test_execute_ha_action_success(monkeypatch) -> None:
    spec, _ = resolve_action_spec("restart_wifi_ap", {})
    assert spec is not None

    def fake_call(domain: str, service: str, service_data: dict | None = None, **kwargs):
        return {"ok": True, "domain": domain, "service": service, "service_data": service_data or {}}

    monkeypatch.setattr("voiceops.adapters.ha_actions.call_ha_service", fake_call)
    monkeypatch.setattr(
        "voiceops.adapters.ha_actions.fetch_entity_state",
        lambda entity_id, **kwargs: {"ok": True, "state": "home", "last_changed": "2026-01-01T00:00:00+00:00"},
    )

    result = execute_ha_action(spec)
    assert result["ok"] is True
    assert result["execution_status"] == "SUCCESS_LIVE"


def test_list_available_controls_includes_catalog() -> None:
    payload = list_available_controls(include_discovery=False)
    assert payload["catalog_count"] >= 1
    assert any(item["catalog_id"] == "restart_wifi_ap_solaryard" for item in payload["catalog"])


def test_governed_execution_uses_ha_service(monkeypatch) -> None:
    monkeypatch.setenv("VOICEOPS_HA_ALLOW_DISCOVERED", "true")
    registry = OperationalStateRegistry()

    def fake_execute(spec, **kwargs):
        return {
            "ok": True,
            "execution_status": "SUCCESS_LIVE",
            "label": spec.label,
            "entity_id": spec.entity_id,
        }

    monkeypatch.setattr("voiceops.adapters.ha_actions.execute_ha_action", fake_execute)

    proposal = registry.propose_action(
        "ha_service",
        "network_wifi",
        {"entity_id": "switch.demo", "verb": "on"},
    )
    spec, _ = resolve_action_spec("ha_service", proposal.payload["parameters"])
    assert spec is not None

    from dataclasses import asdict

    from voiceops.execution_permit import VoiceExecutionPermitManager

    permit_mgr = VoiceExecutionPermitManager(ttl_seconds=60.0)
    permit = permit_mgr.issue(
        session_id="test",
        source_event_id="evt_test",
        action_type="ha_service",
        approval_transcript="Yes authorize",
        proposal=asdict(proposal),
        state_snapshot={},
    )
    result = registry.execute_governed_action(proposal.payload["proposal_id"], permit)
    assert result.details["execution_status"] == "SUCCESS_LIVE"
    assert result.details["ha_execution"]["ok"] is True


def test_tool_list_home_assistant_controls() -> None:
    result = list_home_assistant_controls(include_discovery=False)
    assert "catalog" in result
    assert result["catalog_count"] >= 1
