from __future__ import annotations

import json
import logging
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
    return bool(os.getenv("HASS_URL", "").strip() and os.getenv("HASS_TOKEN", "").strip())


def fetch_entity(entity_id: str, *, timeout: float = 5.0) -> dict[str, Any]:
    """Fetch one Home Assistant entity state via REST API."""
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

    observed_at = entity.get("last_updated") or entity.get("last_changed")
    return {
        "ok": True,
        "entity_id": entity_id,
        "state": entity.get("state"),
        "attributes": entity.get("attributes", {}),
        "observed_at": observed_at,
        "truth": "LIVE",
        "source_provider": f"Home Assistant REST ({base})",
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

    reads = {
        key: fetch_entity(entity_id)
        for key, entity_id in HA_ENTITIES.items()
        if key.startswith(("solar_", "battery_", "grid_", "breaker_"))
    }
    if not any(r.get("ok") for r in reads.values()):
        first_err = next((r for r in reads.values() if not r.get("ok")), {})
        return {
            "truth": "OFFLINE",
            "error": first_err.get("error", "Home Assistant read failed"),
            "reads": reads,
        }

    power = _parse_float(reads.get("solar_output_power", {}).get("state"))
    bat_pct = _parse_float(reads.get("battery_capacity_pct", {}).get("state"))
    bat_v = _parse_float(reads.get("battery_voltage", {}).get("state"))
    grid_v = _parse_float(reads.get("grid_voltage", {}).get("state") or reads.get("breaker_phase_a_voltage", {}).get("state"))
    phase_a_power = _parse_float(reads.get("breaker_phase_a_power", {}).get("state"))
    phase_a_amps = _parse_float(reads.get("breaker_phase_a_current", {}).get("state"))

    observed_times = [r.get("observed_at") for r in reads.values() if r.get("observed_at")]
    observed_at = max(observed_times) if observed_times else None

    mode_attrs = reads.get("solar_output_power", {}).get("attributes", {})
    mode_inferred = mode_attrs.get("mode_inferred", {})

    return {
        "truth": "LIVE",
        "source_provider": reads["solar_output_power"].get("source_provider", "Home Assistant"),
        "observed_at": observed_at,
        "solar_generation_watts": power,
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
        "is_in_alarm": bool(attrs.get("is_in_alarm")),
        "is_triggered": bool(attrs.get("is_triggered")),
        "arm_mode": attrs.get("arm_mode") or alarm.get("state"),
        "monitored_zones_count": len(zones) if zones else 10,
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
        "status": "OPTIMAL" if wan_online else "DEGRADED",
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
        "nvr_host": f"{ip} (NVR Dahua)" if ip else "NVR Dahua",
        "presence": nvr.get("state"),
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
