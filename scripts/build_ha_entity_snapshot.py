#!/usr/bin/env python3
"""Build bundled HA entity snapshot from live API and/or local evidence dumps."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "voiceops" / "data" / "ha_entity_snapshot.json"
SCRATCH = ROOT / "scratch"

ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def _walk(obj: object, found: dict[str, dict[str, str]]) -> None:
    if isinstance(obj, dict):
        entity_id = obj.get("entity_id")
        if isinstance(entity_id, str) and ENTITY_RE.match(entity_id):
            attrs = obj.get("attributes") if isinstance(obj.get("attributes"), dict) else {}
            friendly = obj.get("friendly_name") or attrs.get("friendly_name") or entity_id
            state = str(obj.get("state") or "unknown")
            domain = entity_id.split(".", 1)[0]
            found[entity_id] = {
                "entity_id": entity_id,
                "domain": domain,
                "state": state,
                "friendly_name": str(friendly),
                "source": "scratch_evidence",
            }
        for value in obj.values():
            _walk(value, found)
    elif isinstance(obj, list):
        for item in obj:
            _walk(item, found)


def _from_scratch() -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    if SCRATCH.is_dir():
        for path in SCRATCH.glob("*.json"):
            try:
                _walk(json.loads(path.read_text(encoding="utf-8")), found)
            except (json.JSONDecodeError, OSError):
                continue
    return found


def main() -> None:
    from voiceops.runtime_env import load_runtime_env
    from voiceops.adapters.ha_actions import _controllable_domains, _entity_domain
    from voiceops.adapters.ha_actions import _fetch_all_states

    load_runtime_env()
    entities: dict[str, dict[str, str]] = _from_scratch()
    source = "scratch_evidence"
    live_count = 0

    for state in _fetch_all_states():
        entity_id = str(state.get("entity_id") or "")
        if not ENTITY_RE.match(entity_id):
            continue
        attrs = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
        entities[entity_id] = {
            "entity_id": entity_id,
            "domain": _entity_domain(entity_id),
            "state": str(state.get("state") or "unknown"),
            "friendly_name": str(attrs.get("friendly_name") or entity_id),
            "source": "home_assistant_live",
        }
        live_count += 1
    if live_count:
        source = "home_assistant_live"

    allowed = set(_controllable_domains())
    rows = []
    for item in entities.values():
        domain = item["domain"]
        rows.append(
            {
                **item,
                "controllable": domain in allowed,
            }
        )
    rows.sort(key=lambda row: (row["domain"], row["friendly_name"].lower(), row["entity_id"]))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "entity_count": len(rows),
        "controllable_count": sum(1 for row in rows if row["controllable"]),
        "entities": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(rows)} entities ({payload['controllable_count']} controllable) -> {OUT}")


if __name__ == "__main__":
    main()
