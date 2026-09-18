from __future__ import annotations

import os
from voiceops.adapters.insforge_provider import InsForgeProvider
from voiceops.adapters.instacloud_provider import InstaCloudProvider
from voiceops.governed_tools import inspect_operational_state
from voiceops.operational_state import OperationalStateRegistry


def test_truth_retrofit_subsystem_contracts() -> None:
    registry = OperationalStateRegistry()
    telemetry = registry.get_subsystem_telemetry("all")

    assert telemetry["subsystem"] == "all"
    assert "subsystems" in telemetry

    for sub_name in ["telephony", "solar_power", "network_wifi", "dmx_lighting", "servers_rack"]:
        assert sub_name in telemetry["subsystems"]
        item = telemetry["subsystems"][sub_name]
        assert "source_provider" in item
        assert "truth" in item
        assert item["truth"] in ["LIVE", "REPLAY", "SYNTHETIC", "UNVERIFIED"]
        assert "observed_at" in item
        assert "freshness_seconds" in item
        assert "status" in item


def test_truth_retrofit_individual_inspection_metadata() -> None:
    sol = inspect_operational_state("solar_power")
    assert sol["subsystem"] == "solar_power"
    assert "truth" in sol
    assert "source_provider" in sol
    assert "solar_generation_watts" in sol["data"]
    assert "ac_output_power_watts" in sol["data"]
    if sol["truth"] == "LIVE":
        assert sol["data"]["solar_generation_watts"] is not None
    else:
        assert sol["truth"] == "UNVERIFIED"

    alm = inspect_operational_state("security_alarm")
    assert alm["subsystem"] == "security_alarm"
    assert alm["truth"] in {"LIVE", "UNVERIFIED"}
    assert alm["data"]["monitored_zones_count"] == 10

    cam = inspect_operational_state("video_surveillance")
    assert cam["subsystem"] == "video_surveillance"
    assert cam["truth"] == "LIVE"
    assert len(cam["data"]["channels"]) == 2

    tel = inspect_operational_state("telephony")
    assert tel["subsystem"] == "telephony"
    assert "truth" in tel
    assert "source_provider" in tel
    assert tel["data"]["hardware"] == "Grandstream UCM6104 (Firmware 1.0.20.48)"


def test_insforge_non_blocking_provider() -> None:
    # By default disabled
    ins = InsForgeProvider()
    assert not ins.is_available()

    res_session = ins.start_session("test-session-001")
    assert res_session["mirrored"] is False
    assert res_session["status"] == "disabled_or_unconfigured"

    res_event = ins.append_event("test-session-001", "alarm.triggered", {"zone": "Yard"})
    assert res_event["mirrored"] is False

    res_action = ins.record_action("prop_1", "permit_1", "restart_wifi_ap", "EXECUTED")
    assert res_action["mirrored"] is False


def test_instacloud_non_blocking_provider() -> None:
    # By default disabled
    insta = InstaCloudProvider()
    assert not insta.is_available()

    status = insta.get_status()
    assert status["provider"] == "instacloud"
    assert status["status"] == "NOT_CONNECTED"
    assert status["truth"] == "NOT_CONNECTED"
    assert status["local_canonical"] is True

    plan = insta.plan_deploy()
    assert plan["canonical_stays_local"] is True
