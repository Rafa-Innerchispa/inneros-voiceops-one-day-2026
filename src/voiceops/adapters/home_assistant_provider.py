from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import os
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("voiceops.home_assistant")

# Canonical entity IDs verified against Rafael's Home Assistant deployment.
HA_ENTITIES = {
    "solar_output_power": "sensor.inneros_pi01_solar_output_power",
    "battery_capacity_pct": "sensor.inneros_pi01_solar_battery_capacity",
    "battery_voltage": "sensor.inneros_pi01_solar_battery_voltage",
    "grid_voltage": "sensor.inneros_pi01_solar_grid_voltage",
    "breaker_phase_a_voltage": "sensor.breaker_phase_a_voltage",
    "breaker_phase_a_power": "sensor.breaker_phase_a_power",
    "breaker_phase_a_current": "sensor.breaker_phase_a_current",
    "alarm_panel": "alarm_control_panel.panel_home_ralphi_panel_home_ralphi",
    "nvr_tracker": "device_tracker.nvr_dahua",
    "wan_status": "binary_sensor.unifi_dream_machine_wan_status",
}


def _ha_configured() -> bool:
    if os.getenv('VOICEOPS_LOCAL_HOME', '').lower() == 'true':
        try:
            from inneros_core_runtime.homeassistant_client import configured
            return configured()
        except ImportError:
            return False
    return bool(os.getenv("HASS_URL", "").strip() and os.getenv("HASS_TOKEN", "").strip())


def fetch_entity(entity_id: str, *, timeout: float = 5.0) -> dict[str, Any]:
    """Fetch one Home Assistant entity state via REST API."""
    if os.getenv('VOICEOPS_LOCAL_HOME', '').lower() == 'true':
        if entity_id not in HA_ENTITIES.values():
            return {'ok': False, 'truth': 'UNVERIFIED', 'error': 'Entity outside allowlist'}
        try:
            from inneros_core_runtime.homeassistant_client import get_state
            response = get_state(entity_id)
            if not response.get('ok'):
                return {'ok': False, 'truth': 'OFFLINE', 'error': response.get('error')}
            entity = response['entity']
            attrs = entity.get('attributes') or {}
            observed = attrs.get('updated_at') or entity.get('last_reported') or entity.get('last_updated')
            value = entity.get('state')
            available = value not in (None, 'unavailable', 'unknown')
            age = freshness_seconds(observed)
            stale = entity_id.startswith('sensor.inneros_pi01') and (age is None or age > 180)
            safe_keys = {'unit_of_measurement', 'source_field', 'mode_inferred', 'updated_at', 'friendly_name', 'partition_name', 'zones', 'zones_count', 'arm_mode'}
            return {'ok': available and not stale, 'state': value if available else None,
                'entity_id': entity_id, 'observed_at': observed, 'read_at': datetime.now(timezone.utc).isoformat(),
                'attributes': {k:v for k,v in attrs.items() if k in safe_keys},
                'truth': 'STALE' if stale else 'LIVE' if available else 'UNVERIFIED',
                'source_provider': 'Home Assistant local read-only integration'}
        except Exception as exc:
            return {'ok': False, 'truth': 'OFFLINE', 'error': type(exc).__name__}
    base = os.getenv("HASS_URL", "").strip().rstrip("/")
    token = os.getenv("HASS_TOKEN", "").strip()
    if not base or not token:
        return {
            "ok": False,
            "entity_id": entity_id,
            "error": "HASS_URL or HASS_TOKEN not configured",
            "truth": "UNVERIFIED",
        }

    req = Request(
        f"{base}/api/states/{entity_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            entity = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        return {
            "ok": False,
            "entity_id": entity_id,
            "error": f"HTTP {exc.code}",
            "truth": "OFFLINE",
        }
    except URLError as exc:
        return {
            "ok": False,
            "entity_id": entity_id,
            "error": str(exc),
            "truth": "OFFLINE",
        }

    observed_at = entity.get("attributes", {}).get("updated_at") or entity.get("last_reported") or entity.get("last_updated") or entity.get("last_changed")
    available = entity.get("state") not in (None, "unavailable", "unknown")
    return {
        "ok": available,
        "entity_id": entity_id,
        "state": entity.get("state"),
        "attributes": entity.get("attributes", {}),
        "observed_at": observed_at,
        "truth": "LIVE" if available else "UNVERIFIED",
        "read_at": datetime.now(timezone.utc).isoformat(),
        "source_provider": "Home Assistant REST",
    }


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_solar_telemetry() -> dict[str, Any]:
    """Read solar/battery/grid telemetry from Home Assistant."""
    if not _ha_configured():
        return {"truth": "UNVERIFIED", "error": "Home Assistant not configured"}

    selected = {k:v for k,v in HA_ENTITIES.items() if k.startswith(('solar_', 'battery_', 'grid_', 'breaker_'))}
    with ThreadPoolExecutor(max_workers=7) as pool:
        reads = dict(zip(selected, pool.map(fetch_entity, selected.values())))
    if not any(r.get("ok") for r in reads.values()):
        first_err = next((r for r in reads.values() if not r.get("ok")), {})
        return {
            "truth": "OFFLINE",
            "error": first_err.get("error", "Home Assistant read failed"),
            "reads": reads,
        }

    for result in reads.values():
        if not result.get("ok"):
            result["state"] = None
    power = _parse_float(reads.get("solar_output_power", {}).get("state"))
    bat_pct = _parse_float(reads.get("battery_capacity_pct", {}).get("state"))
    bat_v = _parse_float(reads.get("battery_voltage", {}).get("state"))
    grid_v = _parse_float(reads.get("grid_voltage", {}).get("state") or reads.get("breaker_phase_a_voltage", {}).get("state"))
    phase_a_power = _parse_float(reads.get("breaker_phase_a_power", {}).get("state"))
    if phase_a_power is not None and reads.get('breaker_phase_a_power',{}).get('attributes',{}).get('unit_of_measurement') == 'kW':
        phase_a_power *= 1000
    phase_a_amps = _parse_float(reads.get("breaker_phase_a_current", {}).get("state"))

    observed_times = [r.get("observed_at") for r in reads.values() if r.get("observed_at")]
    observed_at = max(observed_times) if observed_times else None

    mode_attrs = reads.get("solar_output_power", {}).get("attributes", {})
    mode_inferred = mode_attrs.get("mode_inferred", {})

    return {
        "truth": "LIVE" if reads["solar_output_power"].get("ok") else reads["solar_output_power"].get("truth", "UNVERIFIED"),
        "source_provider": reads["solar_output_power"].get("source_provider", "Home Assistant"),
        "observed_at": observed_at,
        "solar_generation_watts": power,
        "inverter_output_watts": power,
        "power_measurement": "AC inverter output, not solar PV generation",
        "battery_charge_pct": bat_pct,
        "battery_voltage_volts": bat_v,
        "grid_voltage_volts": grid_v,
        "phase_a_power_watts": phase_a_power,
        "phase_a_current_amps": phase_a_amps,
        "inferred_mode": mode_inferred.get("mode"),
        "reads": reads,
    }


def read_alarm_telemetry() -> dict[str, Any]:
    if not _ha_configured():
        return {"truth": "UNVERIFIED", "error": "Home Assistant not configured"}

    alarm = fetch_entity(HA_ENTITIES["alarm_panel"])
    if not alarm.get("ok"):
        return {"truth": "OFFLINE", "error": alarm.get("error"), "reads": {"alarm": alarm}}

    attrs = alarm.get("attributes", {})
    zones = [k for k in attrs.keys() if "zone" in k.lower()]
    return {
        "truth": "LIVE",
        "source_provider": alarm.get("source_provider"),
        "observed_at": alarm.get("observed_at"),
        "partition": attrs.get("partition_name") or attrs.get("friendly_name"),
        "device_id": attrs.get("device_id"),
        "is_in_alarm": alarm.get("state") == "triggered",
        "is_triggered": alarm.get("state") == "triggered",
        "arm_mode": attrs.get("arm_mode") or alarm.get("state"),
        "monitored_zones_count": attrs.get("zones_count"),
        "reads": {"alarm": alarm},
    }


def read_network_telemetry() -> dict[str, Any]:
    if not _ha_configured():
        return {"truth": "UNVERIFIED", "error": "Home Assistant not configured"}

    wan = fetch_entity(HA_ENTITIES["wan_status"])
    if not wan.get("ok"):
        return {"truth": "OFFLINE", "error": wan.get("error"), "reads": {"wan": wan}}

    wan_online = str(wan.get("state", "")).lower() in {"on", "online", "connected", "true"}
    return {
        "truth": "LIVE",
        "source_provider": wan.get("source_provider"),
        "observed_at": wan.get("observed_at"),
        "wan_online": wan_online,
        "status": "CONNECTED" if wan_online else "DISCONNECTED",
        "read_at": wan.get("read_at"),
        "observation_scope": "Home Assistant WAN state, not a link-quality measurement",
        "reads": {"wan": wan},
    }


def read_camera_telemetry() -> dict[str, Any]:
    if not _ha_configured():
        return {"truth": "UNVERIFIED", "error": "Home Assistant not configured"}

    nvr = fetch_entity(HA_ENTITIES["nvr_tracker"])
    if not nvr.get("ok"):
        return {"truth": "OFFLINE", "error": nvr.get("error"), "reads": {"nvr": nvr}}

    attrs = nvr.get("attributes", {})
    ip = attrs.get("ip", "unknown")
    return {
        "truth": "LIVE",
        "source_provider": nvr.get("source_provider"),
        "observed_at": nvr.get("observed_at"),
        "nvr_host": "Dahua NVR",
        "stream_status": "UNVERIFIED",
        "motion_status": "UNVERIFIED",
        "presence": nvr.get("state"),
        "read_at": nvr.get("read_at"),
        "reads": {"nvr": nvr},
    }


def freshness_seconds(observed_at: str | None) -> float | None:
    if not observed_at:
        return None
    try:
        ts = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds())
    except ValueError:
        return None
