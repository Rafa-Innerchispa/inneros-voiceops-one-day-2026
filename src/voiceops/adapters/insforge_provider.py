from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


@dataclass
class InsForgeProvider:
    """Optional evidence mirror to InsForge BaaS."""

    api_key: str = field(default_factory=lambda: os.getenv("INSFORGE_API_KEY", ""))
    endpoint: str = field(
        default_factory=lambda: os.getenv("INSFORGE_ENDPOINT", "https://api.insforge.dev/v1")
    )
    project_id: str = field(default_factory=lambda: os.getenv("INSFORGE_PROJECT_ID", ""))
    enabled: bool = field(
        default_factory=lambda: os.getenv("INNEROS_INSFORGE_ENABLED", "false").lower() == "true"
    )

    def connection_status(self) -> dict[str, Any]:
        if not self.enabled or not self.api_key:
            return {
                "status": "INSFORGE NOT CONNECTED - AUTH REQUIRED",
                "truth": "NOT_CONNECTED",
                "mirrored": False,
            }
        return {"status": "CONFIGURED", "truth": "PENDING_VERIFY", "mirrored": False}

    def is_available(self) -> bool:
        return self.enabled and bool(self.api_key)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.is_available():
            return {
                "mirrored": False,
                "provider": "insforge",
                "status": "INSFORGE NOT CONNECTED - AUTH REQUIRED",
                "truth": "NOT_CONNECTED",
            }

        base = self.endpoint.rstrip("/")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = Request(
            f"{base}{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8")
                return {"ok": True, "status_code": resp.status, "body": json.loads(raw) if raw else {}}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            logger.warning("InsForge HTTP %s on %s: %s", exc.code, path, detail)
            return {"ok": False, "status_code": exc.code, "error": detail, "truth": "OFFLINE"}
        except URLError as exc:
            logger.warning("InsForge unreachable on %s: %s", path, exc)
            return {"ok": False, "error": str(exc), "truth": "OFFLINE"}

    def start_session(self, session_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }
        result = self._request("POST", "/voice_sessions", payload)
        if not result.get("ok"):
            return {
                "mirrored": False,
                "provider": "insforge",
                "status": result.get("status", "INSFORGE NOT CONNECTED - AUTH REQUIRED"),
                "truth": result.get("truth", "NOT_CONNECTED"),
                "error": result.get("error"),
            }
        return {
            "mirrored": True,
            "provider": "insforge",
            "truth": "LIVE",
            "session": payload,
            "readback": result.get("body"),
        }

    def append_event(self, session_id: str, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        event_record = {
            "session_id": session_id,
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        insert = self._request("POST", "/timeline_events", event_record)
        if not insert.get("ok"):
            return {
                "mirrored": False,
                "provider": "insforge",
                "status": "INSFORGE NOT CONNECTED - AUTH REQUIRED",
                "truth": insert.get("truth", "NOT_CONNECTED"),
                "error": insert.get("error"),
            }
        readback = self._request("GET", f"/timeline_events?session_id={session_id}&limit=1")
        return {
            "mirrored": True,
            "provider": "insforge",
            "truth": "LIVE",
            "event": event_record,
            "readback": readback.get("body"),
        }

    def record_action(self, proposal_id: str, permit_id: str, action_type: str, result: str) -> dict[str, Any]:
        record = {
            "proposal_id": proposal_id,
            "permit_id": permit_id,
            "action_type": action_type,
            "result": result,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        insert = self._request("POST", "/governed_actions", record)
        if not insert.get("ok"):
            return {
                "mirrored": False,
                "provider": "insforge",
                "status": "INSFORGE NOT CONNECTED - AUTH REQUIRED",
                "truth": insert.get("truth", "NOT_CONNECTED"),
                "error": insert.get("error"),
            }
        readback = self._request("GET", f"/governed_actions?proposal_id={proposal_id}")
        return {
            "mirrored": True,
            "provider": "insforge",
            "truth": "LIVE",
            "action_record": record,
            "readback": readback.get("body"),
        }
