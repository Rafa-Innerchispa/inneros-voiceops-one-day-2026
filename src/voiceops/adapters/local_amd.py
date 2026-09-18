from __future__ import annotations

import json
import os
from typing import Any, Callable
from urllib.request import Request, urlopen

from voiceops.models import ActionProposal
from voiceops.reasoning import ReasoningResult


DEFAULT_ENDPOINT = "http://127.0.0.1:18000/v1/chat/completions"
DEFAULT_MODEL = "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ"


class LocalAMDReasoner:
    """Bounded adapter for the existing local AMD .5 OpenAI-compatible runtime.

    Physical Guardian remains the owner of the action candidate. The model may
    explain or summarize that candidate, but it cannot change the action type,
    approval requirement, or payload before VoiceOps presents it to the human.
    """

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 20.0,
        post_json: Callable[[str, dict[str, Any], float], dict[str, Any]] | None = None,
    ) -> None:
        self.endpoint = endpoint or os.getenv("VOICEOPS_AMD5_URL", DEFAULT_ENDPOINT)
        self.model = model or os.getenv("VOICEOPS_AMD5_MODEL", DEFAULT_MODEL)
        self.timeout_seconds = timeout_seconds
        self._post_json = post_json or _post_json

    def propose(self, facts: dict[str, Any]) -> ReasoningResult:
        candidate = facts.get("action_candidate")
        if not isinstance(candidate, dict):
            return ReasoningResult(
                proposal=ActionProposal(
                    action_type="no_action",
                    summary="Physical Guardian supplied no consequential action candidate.",
                    requires_approval=False,
                    payload={
                        "source_event_id": facts.get("event_id"),
                        "reason_code": "NO_GUARDIAN_ACTION_CANDIDATE",
                    },
                ),
                route={
                    "policy": "local_first",
                    "provider": "local-amd-5",
                    "model": self.model,
                    "external_fallback": False,
                    "truth": "LIVE_NO_MODEL_CALL",
                },
            )

        required = {"action_type", "summary", "requires_approval", "payload"}
        missing = required.difference(candidate)
        if missing:
            raise ValueError(f"Guardian action candidate missing fields: {sorted(missing)}")

        request_payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 180,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the local InnerOS reasoning layer. Given a normalized Physical Guardian event and its "
                        "already-bounded action candidate, return ONLY JSON with one key named summary. Do not invent a "
                        "different action, target, approval policy, or payload. Keep the summary under 220 characters."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "event": {
                                "event_id": facts.get("event_id"),
                                "event_type": facts.get("event_type"),
                                "severity": facts.get("severity"),
                                "source_id": facts.get("source_id"),
                                "zone_id": facts.get("zone_id"),
                                "evidence_refs": facts.get("evidence_refs"),
                            },
                            "action_candidate": candidate,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        response = self._post_json(self.endpoint, request_payload, self.timeout_seconds)
        content = _extract_content(response)
        summary = _extract_summary(content) or str(candidate["summary"])

        return ReasoningResult(
            proposal=ActionProposal(
                action_type=str(candidate["action_type"]),
                summary=summary,
                requires_approval=bool(candidate["requires_approval"]),
                payload=dict(candidate["payload"]),
            ),
            route={
                "policy": "local_first",
                "provider": "local-amd-5",
                "model": self.model,
                "external_fallback": False,
                "truth": "LIVE_MODEL_RESPONSE",
            },
        )

    def analyze_incident(self, query: str, *, subsystem: str = "all", context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Root-cause style incident analysis via local Qwen runtime."""
        request_payload = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": 420,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are InnerOS incident analysis on Node AG-41 in Guayaquil. "
                        "Return ONLY JSON with keys: incident_id, root_cause, recommendation. "
                        "root_cause must mention grid/solar/network/telephony context when relevant."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "query": query,
                            "subsystem": subsystem,
                            "operational_context": context or {},
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        response = self._post_json(self.endpoint, request_payload, self.timeout_seconds)
        content = _extract_content(response)
        parsed = _extract_incident_payload(content)
        return {
            "tool": "inneros_analyze_incident",
            "query": query,
            "subsystem": subsystem,
            "incident_id": parsed.get("incident_id", "INC_UNVERIFIED"),
            "root_cause": parsed.get("root_cause", content),
            "recommendation": parsed.get("recommendation", "Review live telemetry and propose governed remediation."),
            "engine": "InnerOS Local Qwen Engine (AMD Ryzen 9 7900X / Radeon AI PRO R9700)",
            "model": self.model,
            "truth": "LIVE_MODEL_RESPONSE",
        }


def _post_json(endpoint: str, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - configured local runtime endpoint
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict):
        raise ValueError("local AMD response must be a JSON object")
    return body


def _extract_content(response: dict[str, Any]) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("local AMD response missing choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueError("local AMD response content must be non-empty text")
    return content.strip()


def _extract_incident_payload(content: str) -> dict[str, str]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return {"root_cause": cleaned}
    if not isinstance(payload, dict):
        return {"root_cause": cleaned}
    out: dict[str, str] = {}
    for key in ("incident_id", "root_cause", "recommendation"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def _extract_summary(content: str) -> str | None:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    summary = payload.get("summary")
    if not isinstance(summary, str):
        return None
    normalized = " ".join(summary.split())
    return normalized[:220] if normalized else None
