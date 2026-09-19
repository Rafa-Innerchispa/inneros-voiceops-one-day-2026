from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .live_ha_provider import _entity_map, _ha_config, fetch_entity_state

_SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "data" / "ha_entity_snapshot.json"

DEFAULT_CONTROLLABLE_DOMAINS = (
    "light",
    "switch",
    "button",
    "input_button",
    "climate",
    "fan",
    "cover",
    "lock",
    "scene",
    "script",
    "automation",
    "alarm_control_panel",
    "media_player",
    "valve",
    "vacuum",
    "unifi",
)

DEFAULT_ACTION_CATALOG: dict[str, dict[str, Any]] = {
    "restart_wifi_ap_solaryard": {
        "label": "Reiniciar AP-SolarYard (PoE / botón UniFi)",
        "subsystem": "network_wifi",
        "legacy_action_type": "restart_wifi_ap",
        "domain": "button",
        "service": "press",
        "entity_id": "button.unifi_ap_solaryard_restart",
        "verify_entity_id": "device_tracker.ap_solaryard",
        "demo_flag": "ap_solaryard_degraded",
    },
    "restart_wifi_ap_room": {
        "label": "Reiniciar UniFi AP del cuarto",
        "subsystem": "network_wifi",
        "domain": "button",
        "service": "press",
        "entity_id": "button.unifi_ap_cuarto_restart",
        "verify_entity_id": "device_tracker.unifi_cuarto",
    },
}

DOMAIN_DEFAULT_SERVICES: dict[str, str] = {
    "light": "turn_on",
    "switch": "turn_on",
    "button": "press",
    "input_button": "press",
    "scene": "turn_on",
    "script": "turn_on",
    "automation": "trigger",
    "cover": "open",
    "lock": "lock",
    "fan": "turn_on",
    "climate": "set_temperature",
    "media_player": "media_play",
    "vacuum": "start",
    "valve": "open",
}

VERB_SERVICE_MAP: dict[str, dict[str, str]] = {
    "light": {
        "on": "turn_on",
        "off": "turn_off",
        "toggle": "toggle",
    },
    "switch": {
        "on": "turn_on",
        "off": "turn_off",
        "toggle": "toggle",
    },
    "button": {"press": "press", "on": "press"},
    "input_button": {"press": "press", "on": "press"},
    "cover": {"open": "open", "close": "close", "stop": "stop", "toggle": "toggle"},
    "lock": {"lock": "lock", "unlock": "unlock"},
    "fan": {"on": "turn_on", "off": "turn_off", "toggle": "toggle"},
    "scene": {"on": "turn_on", "activate": "turn_on"},
    "script": {"on": "turn_on", "run": "turn_on"},
    "automation": {"on": "trigger", "trigger": "trigger"},
    "alarm_control_panel": {
        "arm": "alarm_arm_home",
        "arm_home": "alarm_arm_home",
        "arm_away": "alarm_arm_away",
        "disarm": "alarm_disarm",
    },
    "media_player": {
        "play": "media_play",
        "pause": "media_pause",
        "stop": "media_stop",
        "on": "turn_on",
        "off": "turn_off",
    },
}


@dataclass(slots=True)
class HaActionSpec:
    catalog_id: str | None
    label: str
    domain: str
    service: str
    entity_id: str | None
    service_data: dict[str, Any] = field(default_factory=dict)
    verify_entity_id: str | None = None
    demo_flag: str | None = None
    subsystem: str = "all"
    steps: list[dict[str, Any]] = field(default_factory=list)


def _controllable_domains() -> tuple[str, ...]:
    raw = os.getenv("VOICEOPS_HA_ACTION_DOMAINS", "").strip()
    if not raw:
        return DEFAULT_CONTROLLABLE_DOMAINS
    domains = tuple(part.strip() for part in raw.split(",") if part.strip())
    return domains or DEFAULT_CONTROLLABLE_DOMAINS


def _action_catalog() -> dict[str, dict[str, Any]]:
    catalog = {key: dict(value) for key, value in DEFAULT_ACTION_CATALOG.items()}
    raw = os.getenv("VOICEOPS_HA_ACTIONS_JSON", "").strip()
    if not raw:
        return catalog
    try:
        override = json.loads(raw)
    except json.JSONDecodeError:
        return catalog
    if not isinstance(override, dict):
        return catalog
    for key, value in override.items():
        if isinstance(key, str) and isinstance(value, dict):
            catalog[key] = {**catalog.get(key, {}), **value}
    return catalog


def _legacy_catalog_lookup(action_type: str) -> dict[str, Any] | None:
    for catalog_id, entry in _action_catalog().items():
        if entry.get("legacy_action_type") == action_type:
            return {"catalog_id": catalog_id, **entry}
    return None


def _entity_domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


def _infer_service(domain: str, verb: str | None) -> str | None:
    if not verb:
        return DOMAIN_DEFAULT_SERVICES.get(domain)
    normalized = verb.strip().lower().replace(" ", "_")
    domain_map = VERB_SERVICE_MAP.get(domain, {})
    if normalized in domain_map:
        return domain_map[normalized]
    if normalized in DOMAIN_DEFAULT_SERVICES.values():
        return normalized
    return DOMAIN_DEFAULT_SERVICES.get(domain)


def _known_entity_ids() -> set[str]:
    known = set(_entity_map().values())
    for entry in _action_catalog().values():
        for key in ("entity_id", "verify_entity_id"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                known.add(value.strip())
        for step in entry.get("steps") or []:
            if isinstance(step, dict):
                entity_id = step.get("entity_id")
                if isinstance(entity_id, str) and entity_id.strip():
                    known.add(entity_id.strip())
    return known


def call_ha_service(
    domain: str,
    service: str,
    service_data: dict[str, Any] | None = None,
    *,
    opener: Callable[..., Any] = urlopen,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Invoke a Home Assistant service via REST API."""
    base, token = _ha_config()
    if not token:
        return {
            "ok": False,
            "error": "HASS_TOKEN not configured on this host; set HASS_TOKEN to execute live actions.",
            "domain": domain,
            "service": service,
        }

    payload = dict(service_data or {})
    url = f"{base.rstrip('/')}/api/services/{domain}/{service}"
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw) if raw.strip() else []
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "error": f"HTTP {exc.code}: {detail[:500]}",
            "domain": domain,
            "service": service,
        }
    except URLError as exc:
        return {"ok": False, "error": str(exc), "domain": domain, "service": service}

    return {
        "ok": True,
        "domain": domain,
        "service": service,
        "service_data": payload,
        "response": parsed,
    }


def _fetch_all_states(
    *,
    opener: Callable[..., Any] = urlopen,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    base, token = _ha_config()
    if not token:
        return []
    request = Request(
        f"{base.rstrip('/')}/api/states",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="GET",
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def load_entity_snapshot() -> dict[str, Any]:
    """Load bundled entity snapshot generated from prior HA reads / evidence dumps."""
    if not _SNAPSHOT_PATH.is_file():
        return {"entities": [], "entity_count": 0, "controllable_count": 0}
    try:
        payload = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"entities": [], "entity_count": 0, "controllable_count": 0}
    if not isinstance(payload, dict):
        return {"entities": [], "entity_count": 0, "controllable_count": 0}
    entities = payload.get("entities")
    if not isinstance(entities, list):
        payload["entities"] = []
    return payload


def _entity_row_from_state(state: dict[str, Any], *, source: str) -> dict[str, Any] | None:
    entity_id = str(state.get("entity_id") or "")
    if not entity_id or "." not in entity_id:
        return None
    domain = _entity_domain(entity_id)
    allowed = set(_controllable_domains())
    attributes = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
    verbs = VERB_SERVICE_MAP.get(domain, {})
    return {
        "entity_id": entity_id,
        "domain": domain,
        "state": state.get("state"),
        "friendly_name": attributes.get("friendly_name") or entity_id,
        "controllable": domain in allowed,
        "supported_verbs": sorted(verbs.keys()) if verbs else (["default"] if domain in allowed else []),
        "default_verb": next(iter(verbs.keys()), None) if verbs else None,
        "source": source,
    }


def discover_all_entities(
    *,
    opener: Callable[..., Any] = urlopen,
    limit: int = 2000,
    controllable_only: bool = False,
    query: str = "",
) -> list[dict[str, Any]]:
    """Merge live HA states with bundled snapshot; optionally filter."""
    merged: dict[str, dict[str, Any]] = {}
    for row in load_entity_snapshot().get("entities") or []:
        if not isinstance(row, dict):
            continue
        entity_id = str(row.get("entity_id") or "")
        if entity_id:
            merged[entity_id] = dict(row)

    live_rows = 0
    for state in _fetch_all_states(opener=opener):
        row = _entity_row_from_state(state, source="home_assistant_live")
        if row:
            merged[row["entity_id"]] = row
            live_rows += 1

    rows = list(merged.values())
    if controllable_only:
        rows = [row for row in rows if row.get("controllable")]
    needle = query.strip().lower()
    if needle:
        rows = [
            row
            for row in rows
            if needle in str(row.get("entity_id", "")).lower()
            or needle in str(row.get("friendly_name", "")).lower()
            or needle in str(row.get("domain", "")).lower()
        ]
    rows.sort(key=lambda item: (str(item.get("domain")), str(item.get("friendly_name", "")).lower()))
    if limit > 0:
        rows = rows[:limit]
    return rows


def discover_controllable_entities(
    *,
    opener: Callable[..., Any] = urlopen,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return HA entities in allowlisted domains that can be acted on after approval."""
    allowed = set(_controllable_domains())
    discovered: list[dict[str, Any]] = []
    for state in _fetch_all_states(opener=opener):
        entity_id = str(state.get("entity_id") or "")
        domain = _entity_domain(entity_id)
        if domain not in allowed:
            continue
        attributes = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
        discovered.append(
            {
                "entity_id": entity_id,
                "domain": domain,
                "state": state.get("state"),
                "friendly_name": attributes.get("friendly_name") or entity_id,
                "supported_services": sorted(VERB_SERVICE_MAP.get(domain, {"default": DOMAIN_DEFAULT_SERVICES.get(domain, "turn_on")}).keys()),
                "default_service": DOMAIN_DEFAULT_SERVICES.get(domain),
            }
        )
        if len(discovered) >= limit:
            break
    discovered.sort(key=lambda item: str(item.get("friendly_name") or item.get("entity_id")))
    return discovered


def list_available_controls(
    *,
    include_discovery: bool = True,
    discovery_limit: int = 2000,
    controllable_only: bool = False,
    query: str = "",
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Catalog + merged entity inventory for operator/agent planning."""
    catalog = _action_catalog()
    catalog_items = [
        {
            "catalog_id": catalog_id,
            "label": entry.get("label") or catalog_id,
            "subsystem": entry.get("subsystem") or "all",
            "domain": entry.get("domain"),
            "service": entry.get("service"),
            "entity_id": entry.get("entity_id"),
            "legacy_action_type": entry.get("legacy_action_type"),
        }
        for catalog_id, entry in catalog.items()
    ]
    base, token = _ha_config()
    snapshot = load_entity_snapshot()
    result: dict[str, Any] = {
        "truth": "LIVE" if token else ("SNAPSHOT" if snapshot.get("entity_count") else "UNVERIFIED"),
        "ha_url": base,
        "token_configured": bool(token),
        "snapshot_generated_at": snapshot.get("generated_at"),
        "snapshot_source": snapshot.get("source"),
        "controllable_domains": list(_controllable_domains()),
        "catalog_count": len(catalog_items),
        "catalog": catalog_items,
        "known_entity_ids": sorted(_known_entity_ids()),
    }
    if include_discovery:
        entities = discover_all_entities(
            opener=opener,
            limit=discovery_limit,
            controllable_only=controllable_only,
            query=query,
        )
        domains: dict[str, int] = {}
        for row in entities:
            domain = str(row.get("domain") or "unknown")
            domains[domain] = domains.get(domain, 0) + 1
        result["entity_count"] = len(entities)
        result["controllable_count"] = sum(1 for row in entities if row.get("controllable"))
        result["domain_counts"] = dict(sorted(domains.items()))
        result["entities"] = entities
        result["discovered_count"] = len(entities)
        result["discovered_entities"] = [row for row in entities if row.get("controllable")]
        if not token:
            result["discovery_note"] = (
                "Using bundled snapshot + evidence until HASS_TOKEN is configured on this host."
            )
    else:
        result["entity_count"] = 0
        result["entities"] = []
        result["discovered_count"] = 0
        result["discovered_entities"] = []
    return result


def resolve_action_spec(
    action_type: str,
    parameters: dict[str, Any] | None = None,
) -> tuple[HaActionSpec | None, str | None]:
    """Resolve a governed proposal into a concrete Home Assistant action."""
    params = dict(parameters or {})
    catalog = _action_catalog()

    catalog_id = params.get("catalog_id")
    if isinstance(catalog_id, str) and catalog_id in catalog:
        entry = catalog[catalog_id]
        return _spec_from_catalog_entry(catalog_id, entry, params), None

    if action_type == "ha_service" or params.get("domain"):
        return _spec_from_explicit_params(action_type, params)

    legacy = _legacy_catalog_lookup(action_type)
    if legacy:
        catalog_id = str(legacy["catalog_id"])
        return _spec_from_catalog_entry(catalog_id, legacy, params), None

    entity_id = params.get("entity_id")
    if isinstance(entity_id, str) and entity_id.strip():
        return _spec_from_entity(entity_id.strip(), params)

    return None, (
        f"No executable Home Assistant mapping for action_type '{action_type}'. "
        "Use list_home_assistant_controls, then propose with catalog_id or ha_service parameters."
    )


def _spec_from_catalog_entry(
    catalog_id: str,
    entry: dict[str, Any],
    params: dict[str, Any],
) -> HaActionSpec:
    steps = entry.get("steps")
    if isinstance(steps, list) and steps:
        first = steps[0] if isinstance(steps[0], dict) else {}
        domain = str(first.get("domain") or entry.get("domain") or "")
        service = str(first.get("service") or entry.get("service") or "")
        entity_id = first.get("entity_id") or entry.get("entity_id")
    else:
        domain = str(entry.get("domain") or "")
        service = str(entry.get("service") or "")
        entity_id = entry.get("entity_id")

    service_data = dict(entry.get("service_data") or {})
    override_data = params.get("service_data")
    if isinstance(override_data, dict):
        service_data.update(override_data)

    if isinstance(entity_id, str) and entity_id.strip():
        service_data.setdefault("entity_id", entity_id.strip())

    label = str(params.get("label") or entry.get("label") or catalog_id)
    return HaActionSpec(
        catalog_id=catalog_id,
        label=label,
        domain=domain,
        service=service,
        entity_id=str(entity_id).strip() if isinstance(entity_id, str) else None,
        service_data=service_data,
        verify_entity_id=_optional_str(entry.get("verify_entity_id")),
        demo_flag=_optional_str(entry.get("demo_flag")),
        subsystem=str(params.get("target_subsystem") or entry.get("subsystem") or "all"),
        steps=[step for step in (steps or []) if isinstance(step, dict)],
    )


def _spec_from_explicit_params(action_type: str, params: dict[str, Any]) -> tuple[HaActionSpec | None, str | None]:
    domain = _optional_str(params.get("domain"))
    service = _optional_str(params.get("service"))
    entity_id = _optional_str(params.get("entity_id"))
    verb = _optional_str(params.get("verb") or params.get("action"))

    if not domain and entity_id:
        domain = _entity_domain(entity_id)
    if domain and not service:
        service = _infer_service(domain, verb)
    if not domain or not service:
        return None, "ha_service requires domain+service or entity_id with inferable verb."

    allowed_domains = set(_controllable_domains())
    if domain not in allowed_domains:
        return None, f"Domain '{domain}' is not in VOICEOPS_HA_ACTION_DOMAINS allowlist."

    if entity_id and not _entity_allowed(entity_id):
        return None, (
            f"Entity '{entity_id}' is not in the governed allowlist. "
            "Add it to VOICEOPS_HA_ACTIONS_JSON or VOICEOPS_HA_ENTITIES_JSON, "
            "or enable VOICEOPS_HA_ALLOW_DISCOVERED=true."
        )

    service_data = dict(params.get("service_data") or {})
    if entity_id:
        service_data.setdefault("entity_id", entity_id)

    label = _optional_str(params.get("label")) or (
        f"{service} on {entity_id}" if entity_id else f"{domain}.{service}"
    )
    return HaActionSpec(
        catalog_id=_optional_str(params.get("catalog_id")),
        label=label or action_type,
        domain=domain,
        service=service,
        entity_id=entity_id,
        service_data=service_data,
        verify_entity_id=_optional_str(params.get("verify_entity_id")),
        demo_flag=_optional_str(params.get("demo_flag")),
        subsystem=str(params.get("target_subsystem") or "all"),
    ), None


def _spec_from_entity(entity_id: str, params: dict[str, Any]) -> tuple[HaActionSpec | None, str | None]:
    domain = _entity_domain(entity_id)
    verb = _optional_str(params.get("verb") or params.get("action") or params.get("service"))
    service = _infer_service(domain, verb)
    if not service:
        return None, f"Cannot infer Home Assistant service for entity '{entity_id}'."
    merged = {**params, "domain": domain, "service": service, "entity_id": entity_id}
    return _spec_from_explicit_params("ha_service", merged)


def _entity_allowed(entity_id: str) -> bool:
    if os.getenv("VOICEOPS_HA_ALLOW_DISCOVERED", "").strip().lower() in {"1", "true", "yes", "on"}:
        domain = _entity_domain(entity_id)
        return domain in set(_controllable_domains())
    if entity_id in _known_entity_ids():
        return True
    for state in _fetch_all_states():
        if str(state.get("entity_id") or "") == entity_id:
            domain = _entity_domain(entity_id)
            return domain in set(_controllable_domains())
    return False


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _run_step(
    step: dict[str, Any],
    *,
    opener: Callable[..., Any],
) -> dict[str, Any]:
    domain = str(step.get("domain") or "")
    service = str(step.get("service") or "")
    service_data = dict(step.get("service_data") or {})
    entity_id = step.get("entity_id")
    if isinstance(entity_id, str) and entity_id.strip():
        service_data.setdefault("entity_id", entity_id.strip())
    delay = float(step.get("delay_seconds") or 0.0)
    result = call_ha_service(domain, service, service_data, opener=opener)
    if delay > 0 and result.get("ok"):
        time.sleep(delay)
    return result


def execute_ha_action(
    spec: HaActionSpec,
    *,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Execute a resolved HA action and optionally verify entity state."""
    step_results: list[dict[str, Any]] = []
    if spec.steps:
        for step in spec.steps:
            step_results.append(_run_step(step, opener=opener))
        ok = all(item.get("ok") for item in step_results)
        primary = step_results[-1] if step_results else {"ok": False, "error": "no steps configured"}
    else:
        primary = call_ha_service(spec.domain, spec.service, spec.service_data, opener=opener)
        step_results = [primary]
        ok = bool(primary.get("ok"))

    verification: dict[str, Any] | None = None
    if ok and spec.verify_entity_id:
        after = fetch_entity_state(spec.verify_entity_id, opener=opener)
        verification = {
            "entity_id": spec.verify_entity_id,
            "ok": bool(after.get("ok")),
            "state": after.get("state"),
            "last_changed": after.get("last_changed"),
        }

    return {
        "ok": ok,
        "execution_status": "SUCCESS_LIVE" if ok else "FAILED",
        "label": spec.label,
        "catalog_id": spec.catalog_id,
        "domain": spec.domain,
        "service": spec.service,
        "entity_id": spec.entity_id,
        "service_data": spec.service_data,
        "steps_executed": len(step_results),
        "step_results": step_results,
        "verification": verification,
        "demo_flag": spec.demo_flag,
    }


def build_action_summary(action_type: str, parameters: dict[str, Any] | None = None) -> str:
    spec, error = resolve_action_spec(action_type, parameters)
    if spec:
        target = spec.entity_id or spec.catalog_id or f"{spec.domain}.{spec.service}"
        return f"{spec.label} → Home Assistant {spec.domain}.{spec.service} on {target}"
    if error:
        return error
    return f"Execute governed operation '{action_type}'"
