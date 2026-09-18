from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class InstaCloudProvider:
    """Optional deployment / preview environment provider adapter for InstaCloud."""

    api_key: str = field(default_factory=lambda: os.getenv("INSTACLOUD_API_KEY", ""))
    project_id: str = field(
        default_factory=lambda: os.getenv("INSTACLOUD_PROJECT_ID", "voiceops-boson")
    )
    enabled: bool = field(
        default_factory=lambda: os.getenv("INNEROS_INSTACLOUD_ENABLED", "false").lower() == "true"
    )

    def is_available(self) -> bool:
        return self.enabled and bool(self.api_key)

    def get_status(self) -> dict[str, Any]:
        """Returns honest InstaCloud status — no fabricated remote deployment."""
        if not self.is_available():
            return {
                "provider": "instacloud",
                "status": "NOT_CONNECTED",
                "truth": "NOT_CONNECTED",
                "preview_url": None,
                "local_canonical": True,
                "note": "InstaCloud adapter skeleton only; no remote deploy probe configured.",
            }
        return {
            "provider": "instacloud",
            "status": "NOT_CONNECTED",
            "truth": "NOT_CONNECTED",
            "project_id": self.project_id,
            "preview_url": None,
            "local_canonical": True,
            "note": "Credentials present but remote InstaCloud deploy API is not wired yet.",
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }

    def plan_deploy(self) -> dict[str, Any]:
        """Generates a non-destructive deployment plan for InstaCloud preview."""
        return {
            "provider": "instacloud",
            "action": "plan_preview",
            "target": "voiceops-boson-preview",
            "requires_human_approval": True,
            "canonical_stays_local": True,
        }
