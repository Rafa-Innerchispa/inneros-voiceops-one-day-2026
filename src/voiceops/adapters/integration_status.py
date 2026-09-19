from __future__ import annotations

import os
import time
from typing import Any

from .boson_realtime import boson_api_key, probe_boson_ready

_BOSON_PROBE_CACHE: dict[str, Any] = {"checked_at": 0.0, "status": None}
_BOSON_PROBE_TTL_SECONDS = 45.0
from .insforge_provider import InsForgeProvider
from .instacloud_provider import InstaCloudProvider
from .live_ha_provider import fetch_ha_snapshot
from .live_telephony_provider import fetch_ami_telephony_snapshot
from .local_amd import LocalAMDReasoner


def _boson_partner_status() -> dict[str, Any]:
    boson_key = boson_api_key()
    if not boson_key:
        return {
            "provider": "Boson AI Higgs Realtime",
            "status": "FALLBACK",
            "truth": "FALLBACK",
            "mode": "browser_fallback",
            "ready": False,
            "remote_confirmed": False,
            "evidence_note": "Browser STT/TTS fallback active (BOSON_API_KEY missing)",
            "token_endpoint": "/api/boson/token",
            "websocket_endpoint": None,
        }

    now = time.monotonic()
    cached = _BOSON_PROBE_CACHE.get("status")
    if cached and (now - float(_BOSON_PROBE_CACHE.get("checked_at") or 0.0)) < _BOSON_PROBE_TTL_SECONDS:
        return dict(cached)

    probed = probe_boson_ready(timeout=10.0)
    if probed.get("ok"):
        status = {
            "provider": "Boson AI Higgs Realtime",
            "status": "CONNECTED",
            "truth": "REAL",
            "mode": "higgs_relay",
            "ready": True,
            "remote_confirmed": True,
            "evidence_note": "Boson Realtime session.created via server-side WebSocket",
            "token_endpoint": "/api/boson/token",
            "websocket_endpoint": "/ws/higgs",
            "model": "higgs-realtime",
            "session_id": probed.get("session_id"),
        }
        _BOSON_PROBE_CACHE.update({"checked_at": now, "status": status})
        return status

    status = {
        "provider": "Boson AI Higgs Realtime",
        "status": "FALLBACK",
        "truth": "FALLBACK",
        "mode": "browser_fallback",
        "ready": True,
        "remote_confirmed": False,
        "evidence_note": "BOSON_API_KEY present but Boson Realtime WebSocket rejected the session",
        "error": probed.get("error"),
        "token_endpoint": "/api/boson/token",
        "websocket_endpoint": None,
    }
    _BOSON_PROBE_CACHE.update({"checked_at": now, "status": status})
    return status


def collect_integration_status() -> dict[str, Any]:
    """Summarize REAL / FALLBACK / NOT_CONNECTED for all partner integrations."""
    boson = _boson_partner_status()
    audio_source = "HIGGS" if boson.get("truth") == "REAL" else "BROWSER_TTS_FALLBACK"

    ha = fetch_ha_snapshot()
    ami = fetch_ami_telephony_snapshot()
    insforge = InsForgeProvider().integration_status()
    instacloud = InstaCloudProvider().get_status()

    qwen_status: dict[str, Any] = {
        "provider": "local-amd-qwen",
        "endpoint": os.getenv("VOICEOPS_AMD5_URL", LocalAMDReasoner().endpoint),
        "truth": "NOT_CONNECTED",
        "status": "NOT_CONNECTED",
    }
    if os.getenv("VOICEOPS_AMD5_URL") or os.getenv("VOICEOPS_AMD5_MODEL"):
        qwen_status["status"] = "CONFIGURED"
        qwen_status["truth"] = "UNVERIFIED"

    partner_integrations = {
        "boson": boson,
        "insforge": insforge,
        "instacloud": instacloud,
    }

    return {
        "audio_source": audio_source,
        "partner_integrations": partner_integrations,
        "boson": boson,
        "home_assistant": {
            "truth": ha.get("truth", "UNVERIFIED"),
            "status": "CONNECTED" if ha.get("truth") == "LIVE" else "NOT_CONNECTED",
            "observed_at": ha.get("observed_at"),
            "errors": ha.get("errors") or [],
        },
        "grandstream_ami": {
            "truth": ami.get("truth", "UNVERIFIED"),
            "status": "CONNECTED" if ami.get("truth") == "LIVE" else "NOT_CONNECTED",
            "error": ami.get("error"),
            "peer_count": ami.get("peer_count", 0),
        },
        "qwen": qwen_status,
        "insforge": insforge,
        "instacloud": instacloud,
    }
