from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

DEFAULT_ENTITIES = {
    "breaker_voltage": "sensor.breaker_phase_a_voltage",
    "breaker_current": "sensor.breaker_phase_a_current",
    "breaker_power": "sensor.breaker_phase_a_power",
    "solar_output_power": "sensor.inneros_pi01_solar_output_power",
    "solar_battery_voltage": "sensor.inneros_pi01_solar_battery_voltage",
    "solar_battery_capacity": "sensor.inneros_pi01_solar_battery_capacity",
    "solar_pv_voltage": "sensor.inneros_pi01_solar_pv_voltage",
    "solar_grid_voltage": "sensor.inneros_pi01_solar_grid_voltage",
    "solar_mode": "sensor.inneros_pi01_solar_mode",
    "alarm_panel": "alarm_control_panel.panel_home_ralphi_panel_home_ralphi",
    "unifi_wan": "binary_sensor.unifi_dream_machine_wan_status",
    "unifi_cpu": "sensor.cloud_gateway_ultra_ralphi_state/cpu_utilization",
}


def _entity_map() -> dict[str, str]:
    mapping = dict(DEFAULT_ENTITIES)
    raw = os.getenv("VOICEOPS_HA_ENTITIES_JSON", "").strip()
    if raw:
        try:
            override = json.loads(raw)
            if isinstance(override, dict):
                for key, value in override.items():
                    if isinstance(key, str) and isinstance(value, str) and value.strip():
                        mapping[key] = value.strip()
        except json.JSONDecodeError:
            pass
    return mapping


def _ha_config() -> tuple[str, str]:
    base = (os.getenv("HASS_URL") or os.getenv("HOME_ASSISTANT_URL") or "").strip().rstrip("/")
    token = (os.getenv("HASS_TOKEN") or os.getenv("HOME_ASSISTANT_TOKEN") or "").strip()
    return base, token


def fetch_entity_state(
    entity_id: str,
    *,
    opener: Callable[..., Any] = urlopen,
    timeout: float = 5.0,
) -> dict[str, Any]:
    base, token = _ha_config()
    if not base or not token:
        return {"ok": False, "entity_id": entity_id, "error": "HASS_URL or HASS_TOKEN not configured"}

    url = f"{base}/api/states/{entity_id}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="GET",
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        return {"ok": False, "entity_id": entity_id, "error": str(exc)}

    if not isinstance(payload, dict):
        return {"ok": False, "entity_id": entity_id, "error": "invalid HA response"}

    last_changed = str(payload.get("last_changed") or payload.get("last_updated") or "")
    return {
        "ok": True,
        "entity_id": entity_id,
        "state": payload.get("state"),
        "attributes": payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {},
        "last_changed": last_changed,
    }


def fetch_ha_snapshot(
    *,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Read configured Home Assistant entities for VoiceOps telemetry."""
    entities = _entity_map()
    readings: dict[str, Any] = {}
    observed_at: str | None = None
    errors: list[str] = []

    for label, entity_id in entities.items():
        result = fetch_entity_state(entity_id, opener=opener)
        if not result.get("ok"):
            errors.append(f"{label}: {result.get('error', 'read failed')}")
            continue
        readings[label] = {
            "entity_id": entity_id,
            "state": result.get("state"),
            "attributes": result.get("attributes"),
            "last_changed": result.get("last_changed"),
        }
        changed = str(result.get("last_changed") or "")
        if changed and (observed_at is None or changed > observed_at):
            observed_at = changed

    if not readings:
        return {
            "truth": "UNVERIFIED",
            "source_provider": "Home Assistant Core REST API",
            "observed_at": None,
            "freshness_seconds": None,
            "readings": {},
            "errors": errors or ["no HA entities readable"],
        }

    freshness = None
    if observed_at:
        try:
            observed_dt = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            freshness = max(0.0, (datetime.now(timezone.utc) - observed_dt).total_seconds())
        except ValueError:
            freshness = None

    return {
        "truth": "LIVE",
        "source_provider": "Home Assistant Core REST API",
        "observed_at": observed_at,
        "freshness_seconds": freshness,
        "readings": readings,
        "errors": errors,
    }
