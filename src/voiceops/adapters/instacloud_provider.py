from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen


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

    def _deployment_id(self) -> str:
        return os.getenv("INSTACLOUD_DEPLOYMENT_ID", f"{self.project_id}-preview").strip()

    def _preview_url(self) -> str | None:
        url = os.getenv("INSTACLOUD_PREVIEW_URL", "").strip().rstrip("/")
        return url or None

    def _status_url(self) -> str | None:
        explicit = os.getenv("INSTACLOUD_STATUS_URL", "").strip()
        if explicit:
            return explicit
        preview = self._preview_url()
        if preview:
            return f"{preview}/healthz"
        return None

    def dashboard_url(self) -> str | None:
        url = os.getenv("INSTACLOUD_DASHBOARD_URL", "").strip()
        return url or None

    def _probe_remote(
        self,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout: float = 5.0,
    ) -> dict[str, Any] | None:
        status_url = self._status_url()
        if not status_url:
            return None

        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = Request(status_url, headers=headers, method="GET")
        try:
            with opener(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                payload: Any = {}
                if raw.strip():
                    payload = json.loads(raw)
                healthy = response.status == 200 and (
                    (isinstance(payload, dict) and payload.get("ok") is True)
                    or (isinstance(payload, dict) and str(payload.get("status", "")).lower() == "healthy")
                    or response.status == 200
                )
                if not healthy:
                    return None
                return {
                    "status_url": status_url,
                    "payload": payload if isinstance(payload, dict) else {},
                }
        except (URLError, json.JSONDecodeError, TimeoutError, OSError):
            return None

    def get_status(
        self,
        *,
        opener: Callable[..., Any] = urlopen,
    ) -> dict[str, Any]:
        """Returns honest InstaCloud status — REAL only after remote health probe succeeds."""
        deployment_id = self._deployment_id()
        preview_url = self._preview_url()
        dashboard_url = self.dashboard_url()
        observed_at = datetime.now(timezone.utc).isoformat()

        if not self.is_available():
            return {
                "provider": "instacloud",
                "status": "NOT_CONNECTED",
                "truth": "NOT_CONNECTED",
                "deployment_id": deployment_id,
                "preview_url": preview_url,
                "dashboard_url": dashboard_url,
                "local_canonical": True,
                "note": "InstaCloud adapter disabled or missing INSTACLOUD_API_KEY.",
                "observed_at": observed_at,
            }

        if not preview_url and not self._status_url():
            return {
                "provider": "instacloud",
                "status": "NOT_CONNECTED",
                "truth": "NOT_CONNECTED",
                "deployment_id": deployment_id,
                "preview_url": None,
                "dashboard_url": dashboard_url,
                "local_canonical": True,
                "note": "Credentials present but INSTACLOUD_PREVIEW_URL / INSTACLOUD_STATUS_URL not configured.",
                "observed_at": observed_at,
            }

        probe = self._probe_remote(opener=opener)
        if probe:
            return {
                "provider": "instacloud",
                "status": "CONNECTED",
                "truth": "REAL",
                "deployment_id": deployment_id,
                "deployment_status": "HEALTHY",
                "preview_url": preview_url,
                "status_url": probe["status_url"],
                "dashboard_url": dashboard_url,
                "local_canonical": True,
                "remote_confirmed": True,
                "observed_at": observed_at,
            }

        return {
            "provider": "instacloud",
            "status": "DISCONNECTED",
            "truth": "NOT_CONNECTED",
            "deployment_id": deployment_id,
            "preview_url": preview_url,
            "status_url": self._status_url(),
            "dashboard_url": dashboard_url,
            "local_canonical": True,
            "remote_confirmed": False,
            "note": "Remote preview configured but health probe failed or returned unhealthy.",
            "observed_at": observed_at,
        }

    def plan_deploy(self) -> dict[str, Any]:
        """Generates a non-destructive deployment plan for InstaCloud preview."""
        return {
            "provider": "instacloud",
            "action": "plan_preview",
            "target": self._deployment_id(),
            "requires_human_approval": True,
            "canonical_stays_local": True,
        }
