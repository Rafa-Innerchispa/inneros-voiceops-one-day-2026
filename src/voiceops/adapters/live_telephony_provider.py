from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from .grandstream_ami import AMIAuthenticationError, AMIError, GrandstreamAMIAdapter


def fetch_ami_telephony_snapshot() -> dict[str, Any]:
    """Read-only Grandstream AMI snapshot for registered SIP peers."""
    host = os.getenv("VOICEOPS_TELEPHONY_AMI_HOST", "").strip()
    if not host:
        return {
            "truth": "UNVERIFIED",
            "source_provider": "Grandstream AMI TCP 7777",
            "observed_at": None,
            "freshness_seconds": None,
            "registered_extensions": [],
            "error": "VOICEOPS_TELEPHONY_AMI_HOST not configured",
        }

    try:
        adapter = GrandstreamAMIAdapter()
        peers = adapter.list_sip_peers()
        core = adapter.core_status()
    except (AMIError, AMIAuthenticationError, ValueError) as exc:
        return {
            "truth": "UNVERIFIED",
            "source_provider": f"Grandstream AMI TCP 7777 ({host})",
            "observed_at": None,
            "freshness_seconds": None,
            "registered_extensions": [],
            "error": str(exc),
        }

    extensions: list[dict[str, str]] = []
    for row in peers:
        if row.get("Event") != "PeerEntry":
            continue
        peer = str(row.get("ObjectName") or row.get("Peer") or "").strip()
        if not peer:
            continue
        status = str(row.get("Status") or row.get("PeerStatus") or "UNKNOWN").upper()
        online = "OK" in status or "REACHABLE" in status or "UNMONITORED" in status
        ext = peer.split("/")[-1] if "/" in peer else peer
        extensions.append(
            {
                "ext": ext,
                "label": peer,
                "status": "ONLINE" if online else status,
                "peer": peer,
            }
        )

    observed_at = datetime.now(timezone.utc).isoformat()
    return {
        "truth": "LIVE",
        "source_provider": f"Grandstream AMI TCP 7777 ({host})",
        "observed_at": observed_at,
        "freshness_seconds": 0.0,
        "registered_extensions": extensions,
        "core_status": core,
        "peer_count": len(extensions),
    }
