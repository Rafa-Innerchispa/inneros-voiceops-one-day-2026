from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


@dataclass
class InsForgeProvider:
    """Non-blocking BaaS / evidence plane adapter for InsForge.

    Local VoiceOps evidence remains canonical. Remote writes are best-effort
    and only marked mirrored when insert + readback succeed.
    """

    api_key: str = field(default_factory=lambda: os.getenv("INSFORGE_API_KEY", ""))
    endpoint: str = field(
        default_factory=lambda: os.getenv("INSFORGE_ENDPOINT", "https://api.insforge.dev/v1")
    )
    rest_url: str = field(default_factory=lambda: os.getenv("INSFORGE_REST_URL", "").strip())
    enabled: bool = field(
        default_factory=lambda: os.getenv("INNEROS_INSFORGE_ENABLED", "false").lower() == "true"
    )

    def is_available(self) -> bool:
        return self.enabled and bool(self.api_key) and bool(self._rest_base())

    def _rest_base(self) -> str:
        if self.rest_url:
            return self.rest_url.rstrip("/")
        endpoint = self.endpoint.rstrip("/")
        if "/rest/v1" in endpoint:
            return endpoint.split("/rest/v1", 1)[0] + "/rest/v1"
        return f"{endpoint}/rest/v1"

    def health_status(self) -> dict[str, Any]:
        if not self.enabled:
            return {"provider": "insforge", "status": "NOT_CONNECTED", "truth": "NOT_CONNECTED"}
        if not self.api_key:
            return {
                "provider": "insforge",
                "status": "NOT_CONNECTED",
                "truth": "NOT_CONNECTED",
                "error": "INSFORGE_API_KEY missing",
            }
        try:
            self._request("GET", "voice_sessions", params={"limit": "1"})
            return {"provider": "insforge", "status": "CONNECTED", "truth": "LIVE", "rest_url": self._rest_base()}
        except Exception as exc:
            return {
                "provider": "insforge",
                "status": "DISCONNECTED",
                "truth": "UNVERIFIED",
                "error": str(exc),
                "rest_url": self._rest_base(),
            }

    def start_session(self, session_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.is_available():
            return {"mirrored": False, "provider": "insforge", "status": "disabled_or_unconfigured"}

        payload = {
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }
        try:
            inserted = self._insert_row("voice_sessions", payload)
            readback = self._readback_row("voice_sessions", inserted, match_key="session_id", match_value=session_id)
            return {
                "mirrored": bool(readback),
                "remote_confirmed": bool(readback),
                "provider": "insforge",
                "session": readback or inserted,
            }
        except Exception as exc:
            logger.warning("InsForge session mirror failed: %s", exc)
            return {"mirrored": False, "provider": "insforge", "status": "remote_error", "error": str(exc)}

    def append_event(self, session_id: str, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self.is_available():
            return {"mirrored": False, "provider": "insforge", "status": "disabled_or_unconfigured"}

        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        event_record = {
            "event_id": event_id,
            "session_id": session_id,
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        try:
            inserted = self._insert_row("timeline_events", event_record)
            readback = self._readback_row("timeline_events", inserted, match_key="event_id", match_value=event_id)
            return {
                "mirrored": bool(readback),
                "remote_confirmed": bool(readback),
                "provider": "insforge",
                "event": readback or inserted,
            }
        except Exception as exc:
            logger.warning("InsForge event mirror failed: %s", exc)
            return {"mirrored": False, "provider": "insforge", "status": "remote_error", "error": str(exc)}

    def record_action(self, proposal_id: str, permit_id: str, action_type: str, result: str) -> dict[str, Any]:
        if not self.is_available():
            return {"mirrored": False, "provider": "insforge", "status": "disabled_or_unconfigured"}

        record = {
            "proposal_id": proposal_id,
            "permit_id": permit_id,
            "action_type": action_type,
            "result": result,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            inserted = self._insert_row("governed_actions", record)
            readback = self._readback_row(
                "governed_actions",
                inserted,
                match_key="permit_id",
                match_value=permit_id,
            )
            return {
                "mirrored": bool(readback),
                "remote_confirmed": bool(readback),
                "provider": "insforge",
                "action_record": readback or inserted,
            }
        except Exception as exc:
            logger.warning("InsForge action mirror failed: %s", exc)
            return {"mirrored": False, "provider": "insforge", "status": "remote_error", "error": str(exc)}

    def _insert_row(self, table: str, row: dict[str, Any], *, opener: Callable[..., Any] = urlopen) -> dict[str, Any]:
        response = self._request("POST", table, body=row, prefer="return=representation", opener=opener)
        if isinstance(response, list) and response:
            first = response[0]
            if isinstance(first, dict):
                return first
        if isinstance(response, dict):
            return response
        return row

    def _readback_row(
        self,
        table: str,
        inserted: dict[str, Any],
        *,
        match_key: str,
        match_value: str,
        opener: Callable[..., Any] = urlopen,
    ) -> dict[str, Any] | None:
        if inserted.get(match_key) == match_value:
            return inserted
        rows = self._request(
            "GET",
            table,
            params={match_key: f"eq.{match_value}", "limit": "1"},
            opener=opener,
        )
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            return rows[0]
        return None

    def _request(
        self,
        method: str,
        table: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        prefer: str | None = None,
        opener: Callable[..., Any] = urlopen,
        timeout: float = 8.0,
    ) -> Any:
        query = ""
        if params:
            query = "?" + "&".join(f"{quote(k)}={quote(v)}" for k, v in params.items())
        url = f"{self._rest_base()}/{table}{query}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "apikey": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with opener(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                if not raw.strip():
                    return {}
                return json.loads(raw)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"InsForge HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"InsForge unreachable: {exc}") from exc
