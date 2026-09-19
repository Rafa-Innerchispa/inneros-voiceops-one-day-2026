from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_SESSION_ID = "boson-live-session"
_session_started = False


def mirror_voiceops_event(
    event_type: str,
    data: dict[str, Any],
    *,
    session_id: str = DEFAULT_SESSION_ID,
) -> dict[str, Any]:
    """Best-effort InsForge evidence mirror; never blocks VoiceOps execution."""
    global _session_started
    from .insforge_provider import InsForgeProvider

    provider = InsForgeProvider()
    if not provider.is_available():
        return {"mirrored": False, "provider": "insforge", "status": "disabled_or_unconfigured"}

    try:
        if not _session_started:
            provider.start_session(session_id, metadata={"source": "inneros-voiceops"})
            _session_started = True
        return provider.append_event(session_id, event_type, data)
    except Exception as exc:
        logger.warning("InsForge mirror skipped: %s", exc)
        return {"mirrored": False, "provider": "insforge", "status": "remote_error", "error": str(exc)}


def mirror_governed_action(
    proposal_id: str,
    permit_id: str,
    action_type: str,
    result: str,
) -> dict[str, Any]:
    """Mirror governed action result to InsForge with insert + readback."""
    from .insforge_provider import InsForgeProvider

    provider = InsForgeProvider()
    if not provider.is_available():
        return {"mirrored": False, "provider": "insforge", "status": "disabled_or_unconfigured"}

    try:
        return provider.record_action(proposal_id, permit_id, action_type, result)
    except Exception as exc:
        logger.warning("InsForge action mirror skipped: %s", exc)
        return {"mirrored": False, "provider": "insforge", "status": "remote_error", "error": str(exc)}
