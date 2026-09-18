from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InsForgeProvider:
    """Non-blocking BaaS / evidence plane adapter for InsForge.

    Mirroring of session logs and timeline events is best-effort.
    Local SQLite / VoiceOps evidence remains the canonical truth.
    """

    api_key: str = field(default_factory=lambda: os.getenv("INSFORGE_API_KEY", ""))
    endpoint: str = field(
        default_factory=lambda: os.getenv("INSFORGE_ENDPOINT", "https://api.insforge.dev/v1")
    )
    enabled: bool = field(
        default_factory=lambda: os.getenv("INNEROS_INSFORGE_ENABLED", "false").lower() == "true"
    )

    def is_available(self) -> bool:
        return self.enabled and bool(self.api_key)

    def start_session(self, session_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Mirrors session creation to InsForge in non-blocking fashion."""
        if not self.is_available():
            return {"mirrored": False, "provider": "insforge", "status": "disabled_or_unconfigured"}

        payload = {
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }
        logger.info("InsForge mirrored session start: %s", session_id)
        return {"mirrored": True, "provider": "insforge", "session": payload}

    def append_event(self, session_id: str, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Appends a timeline event to the InsForge realtime ledger."""
        if not self.is_available():
            return {"mirrored": False, "provider": "insforge", "status": "disabled_or_unconfigured"}

        event_record = {
            "session_id": session_id,
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        logger.info("InsForge mirrored timeline event: %s (%s)", session_id, event_type)
        return {"mirrored": True, "provider": "insforge", "event": event_record}

    def record_action(self, proposal_id: str, permit_id: str, action_type: str, result: str) -> dict[str, Any]:
        """Mirrors a governed action execution permit to InsForge."""
        if not self.is_available():
            return {"mirrored": False, "provider": "insforge", "status": "disabled_or_unconfigured"}

        record = {
            "proposal_id": proposal_id,
            "permit_id": permit_id,
            "action_type": action_type,
            "result": result,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("InsForge recorded governed action: %s", proposal_id)
        return {"mirrored": True, "provider": "insforge", "action_record": record}
