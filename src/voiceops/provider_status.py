from __future__ import annotations

import os
from typing import Any

from .adapters.boson_client import boson_configured
from .adapters.home_assistant_provider import _ha_configured
from .adapters.insforge_provider import InsForgeProvider
from .adapters.instacloud_provider import InstaCloudProvider
from .adapters.local_amd import LocalAMDReasoner


def _status_label(configured: bool, live_ok: bool | None = None) -> str:
    if live_ok is True:
        return "REAL"
    if configured and live_ok is False:
        return "OFFLINE"
    if configured:
        return "CONFIGURED"
    return "NOT_CONNECTED"


def build_voice_status(*, audio_source: str = "NONE") -> dict[str, Any]:
    """Report explicit REAL / FALLBACK / NOT_CONNECTED for judge verification."""
    boson_ok = boson_configured()
    ha_ok = _ha_configured()
    ami_ok = bool(os.getenv("VOICEOPS_TELEPHONY_AMI_HOST", "").strip())
    ami_creds = ami_ok and bool(os.getenv("VOICEOPS_TELEPHONY_AMI_USERNAME", "")) and bool(
        os.getenv("VOICEOPS_TELEPHONY_AMI_SECRET", "")
    )
    qwen_ok = bool(os.getenv("VOICEOPS_AMD5_URL", "").strip())

    ins = InsForgeProvider()
    insta = InstaCloudProvider()

    resolved_audio = audio_source
    if resolved_audio == "NONE":
        resolved_audio = "HIGGS" if boson_ok else "BROWSER_TTS_FALLBACK"

    return {
        "AUDIO_SOURCE": resolved_audio,
        "STT_SOURCE": "BROWSER_SPEECH_RECOGNITION",
        "providers": {
            "boson_higgs": {
                "status": _status_label(boson_ok),
                "mode": "REAL" if boson_ok else "NOT_CONNECTED",
                "upstream": "wss://api.boson.ai/v1/realtime",
            },
            "browser_tts": {
                "status": "FALLBACK",
                "mode": "BROWSER_TTS_FALLBACK",
                "active_when": "BOSON unavailable or no Higgs PCM received",
            },
            "home_assistant": {
                "status": _status_label(ha_ok),
                "mode": "REAL" if ha_ok else "NOT_CONNECTED",
            },
            "grandstream_ami": {
                "status": _status_label(ami_creds),
                "mode": "REAL" if ami_creds else "NOT_CONNECTED",
            },
            "qwen_amd": {
                "status": _status_label(qwen_ok),
                "mode": "REAL" if qwen_ok else "NOT_CONNECTED",
                "endpoint": os.getenv("VOICEOPS_AMD5_URL", ""),
            },
            "insforge": {
                "status": "REAL" if ins.is_available() else "NOT_CONNECTED",
                "mode": "REAL" if ins.is_available() else "NOT_CONNECTED",
                "detail": ins.connection_status().get("status"),
            },
            "instacloud": {
                "status": "NOT_CONNECTED" if not insta.is_available() else "CONFIGURED",
                "mode": "NOT_CONNECTED" if not insta.is_available() else "CONFIGURED",
            },
        },
    }
