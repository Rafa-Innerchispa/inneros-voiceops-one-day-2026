from __future__ import annotations

import os
from typing import Any

from .boson_realtime import boson_api_key
from .insforge_provider import InsForgeProvider
from .instacloud_provider import InstaCloudProvider
from .live_ha_provider import fetch_ha_snapshot
from .live_telephony_provider import fetch_ami_telephony_snapshot
from .local_amd import LocalAMDReasoner


def collect_integration_status() -> dict[str, Any]:
    """Summarize REAL / FALLBACK / NOT_CONNECTED for all partner integrations."""
    boson_key = boson_api_key()
    boson_mode = "higgs_relay" if boson_key else "browser_fallback"
    audio_source = "HIGGS" if boson_key else "BROWSER_TTS_FALLBACK"

    ha = fetch_ha_snapshot()
    ami = fetch_ami_telephony_snapshot()
    insforge = InsForgeProvider().health_status()
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

    return {
        "audio_source": audio_source,
        "boson": {
            "mode": boson_mode,
            "ready": bool(boson_key),
            "truth": "LIVE" if boson_key else "BROWSER_TTS_FALLBACK",
            "provider": "Boson AI Higgs Realtime",
        },
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
        "instacloud": {
            **instacloud,
            "truth": "NOT_CONNECTED" if not InstaCloudProvider().is_available() else "UNVERIFIED",
        },
    }
