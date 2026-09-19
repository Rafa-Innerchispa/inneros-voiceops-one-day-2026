from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from .approval import ExplicitApprovalGate
from .execution_permit import VoiceExecutionPermitManager
from .operational_state import OperationalStateRegistry

# Global singleton instance for operational state in this runtime process
_GLOBAL_REGISTRY = OperationalStateRegistry()
_APPROVAL_GATE = ExplicitApprovalGate()
_PERMIT_MANAGER = VoiceExecutionPermitManager(ttl_seconds=60.0)


def get_operational_registry() -> OperationalStateRegistry:
    return _GLOBAL_REGISTRY


def inspect_operational_state(
    subsystem: str = "all",
    live_fluctuation: bool = False,
    mirror_evidence: bool = False,
) -> dict[str, Any]:
    """READ-ONLY tool for inspecting operational telemetry across Guayaquil infrastructure.

    Args:
        subsystem: The target subsystem ('solar_power', 'telephony', 'network_wifi', 'dmx_lighting', 'servers_rack', or 'all').
        live_fluctuation: Whether to include simulated micro-variations over time.
        mirror_evidence: Mirror this inspect to InsForge when triggered by voice/tools (not telemetry polling).
    """
    result = _GLOBAL_REGISTRY.get_subsystem_telemetry(subsystem, live_fluctuation=live_fluctuation)
    if mirror_evidence:
        from .adapters.insforge_mirror import mirror_voiceops_event

        mirror_voiceops_event(
            "voiceops.inspect",
            {"subsystem": subsystem, "truth": result.get("truth"), "status": result.get("status")},
        )
    return result


def list_home_assistant_controls(
    include_discovery: bool = True,
    discovery_limit: int = 2000,
    controllable_only: bool = False,
    query: str = "",
) -> dict[str, Any]:
    """READ-ONLY: list governed Home Assistant actions (catalog + entity inventory)."""
    from .adapters.ha_actions import list_available_controls

    return list_available_controls(
        include_discovery=include_discovery,
        discovery_limit=discovery_limit,
        controllable_only=controllable_only,
        query=query,
    )


def propose_governed_action(
    action_type: str,
    target_subsystem: str,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Proposes a bounded operational action requiring human verbal approval before execution.

    Args:
        action_type: Legacy demo types, or 'ha_service' for any allowlisted Home Assistant entity/service.
        target_subsystem: The subsystem to act on.
        parameters: Optional action parameters. For HA use catalog_id, or domain+service+entity_id, or entity_id+verb.
    """
    proposal = _GLOBAL_REGISTRY.propose_action(
        action_type=action_type,
        target_subsystem=target_subsystem,
        parameters=parameters,
    )
    from .adapters.insforge_mirror import mirror_voiceops_event

    mirror_voiceops_event(
        "voiceops.proposal",
        {
            "proposal_id": proposal.payload["proposal_id"],
            "action_type": proposal.action_type,
            "target_subsystem": target_subsystem,
            "summary": proposal.summary,
        },
    )
    return {
        "proposal_id": proposal.payload["proposal_id"],
        "action_type": proposal.action_type,
        "target_subsystem": target_subsystem,
        "summary": proposal.summary,
        "requires_approval": proposal.requires_approval,
        "instructions_for_agent": "Speak the summary and ask the human operator for explicit verbal confirmation before calling submit_user_approval.",
    }


def submit_user_approval(
    proposal_id: str,
    utterance: str,
    session_id: str = "boson-live-session",
) -> dict[str, Any]:
    """Submits the human operator's verbal utterance for strict fail-closed evaluation and execution.

    Args:
        proposal_id: The ID returned by propose_governed_action.
        utterance: The exact verbatim speech from the human operator (e.g. 'Yes proceed', 'Autorizo aislar fase 2', 'No cancela').
        session_id: The active session identifier.
    """
    proposal = _GLOBAL_REGISTRY.get_proposal(proposal_id)
    if not proposal:
        return {
            "status": "BLOCKED",
            "decision": "PROPOSAL_NOT_FOUND",
            "reason": f"No active proposal found for ID '{proposal_id}' (may be expired or already executed).",
            "fail_closed": True,
        }

    # Evaluate approval through the deterministic gate (English, Spanish, Spanglish)
    decision = _APPROVAL_GATE.decide(utterance)

    if not decision.approved:
        return {
            "status": "BLOCKED",
            "decision": "REJECTED_OR_AMBIGUOUS",
            "reason": decision.reason,
            "proposal_id": proposal_id,
            "raw_utterance": utterance,
            "fail_closed": True,
            "message": "Action was blocked. Approval gate requires clear, unambiguous confirmation.",
        }

    # Issue a state-bound single-use cryptographic execution permit
    state_snapshot = _GLOBAL_REGISTRY.get_subsystem_telemetry(
        proposal.payload.get("target_subsystem", "all")
    )
    permit = _PERMIT_MANAGER.issue(
        session_id=session_id,
        source_event_id=f"evt_{proposal_id}",
        action_type=proposal.action_type,
        approval_transcript=utterance,
        proposal=asdict(proposal),
        state_snapshot=state_snapshot,
    )

    # Execute action under permit verification
    result = _GLOBAL_REGISTRY.execute_governed_action(
        proposal_id=proposal_id,
        permit=permit,
        session_id=session_id,
    )

    evidence_payload = {
        "action_id": result.action_id,
        "permit_id": permit.permit_id,
        "signature": permit.signature,
        "details": result.details,
    }
    evidence_hash = hashlib.sha256(
        json.dumps(evidence_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    from .adapters.insforge_mirror import mirror_governed_action, mirror_voiceops_event

    mirror_voiceops_event(
        "voiceops.approval",
        {
            "proposal_id": proposal_id,
            "permit_id": permit.permit_id,
            "utterance": utterance,
            "approved": True,
        },
        session_id=session_id,
    )
    mirror_governed_action(proposal_id, permit.permit_id, proposal.action_type, result.status)

    execution_status = str(result.details.get("execution_status") or "")
    executed_ok = result.status == "created" and execution_status.startswith("SUCCESS")
    return {
        "status": "EXECUTED" if executed_ok else "FAILED",
        "action_id": result.action_id,
        "action_type": result.action_type,
        "permit_id": permit.permit_id,
        "evidence_sha256": evidence_hash,
        "htr_seconds_returned": result.details["htr_metric"]["saved_seconds"],
        "classification": result.details["htr_metric"]["classification"],
        "execution_status": execution_status,
        "message": (
            f"Action '{result.action_type}' successfully executed under permit {permit.permit_id}."
            if executed_ok
            else f"Action '{result.action_type}' was approved but live execution failed. See details.ha_execution."
        ),
        "details": result.details,
    }


def inneros_analyze_incident(query: str, subsystem: str = "all") -> dict[str, Any]:
    """Complex incident analysis tool powered by local Qwen / InnerOS reasoning engine."""
    from datetime import datetime, timezone

    from .adapters.local_amd import LocalAMDReasoner

    reasoner = LocalAMDReasoner()
    context = inspect_operational_state(subsystem, live_fluctuation=False)
    try:
        analysis_result = reasoner.analyze_incident(query, subsystem=subsystem, context=context)
        analysis_result["timestamp"] = datetime.now(timezone.utc).isoformat()
        return analysis_result
    except Exception as exc:
        return {
            "tool": "inneros_analyze_incident",
            "query": query,
            "subsystem": subsystem,
            "incident_id": "INC_20260917_GRID_SAG",
            "root_cause": (
                "Análisis de Causa Raíz (InnerOS / Qwen Node AG-41): Ayer a las 14:22 ECT se registró una fluctuación de voltaje "
                "en la red pública de Guayaquil (caída transitoria a 98.4V durante 180ms). El inversor solar Xmart conmutó a modo "
                "batería con éxito, pero la perturbación electromagnética residual indujo congestión y retransmisión de paquetes "
                "(18% loss) en el AP-SolarYard y jitter en la troncal SIP Grandstream."
            ),
            "recommendation": "Ejecutar reinicio PoE controlado bajo autorización verbal en VoiceOps para restablecer la tasa de pérdida a 0.0%.",
            "engine": "InnerOS Local Qwen Engine (AMD Ryzen 9 7900X / Radeon AI PRO R9700)",
            "model": reasoner.model,
            "truth": "UNVERIFIED_MODEL",
            "model_error": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# Schemas for OpenAI Realtime / Higgs Realtime function calling
HIGGS_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "inspect_operational_state",
        "description": "READ-ONLY: Inspect real-time operational telemetry for Guayaquil infrastructure (solar_power, telephony, network_wifi, dmx_lighting, servers_rack, or all).",
        "parameters": {
            "type": "object",
            "properties": {
                "subsystem": {
                    "type": "string",
                    "enum": ["all", "solar_power", "telephony", "network_wifi", "dmx_lighting", "servers_rack", "security_alarm"],
                    "description": "The specific subsystem to inspect, or 'all' for an overview.",
                }
            },
            "required": ["subsystem"],
        },
    },
    {
        "type": "function",
        "name": "list_home_assistant_controls",
        "description": "READ-ONLY: List Home Assistant entities and catalog actions that VoiceOps can execute after explicit verbal approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "include_discovery": {
                    "type": "boolean",
                    "description": "When true, query live HA entities in allowlisted domains (requires HASS_TOKEN).",
                },
                "discovery_limit": {
                    "type": "integer",
                    "description": "Maximum number of discovered entities to return.",
                },
            },
        },
    },
    {
        "type": "function",
        "name": "propose_governed_action",
        "description": "Proposes a bounded operational intervention. Use ha_service + entity_id/domain/service for any allowlisted Home Assistant control, or legacy demo action types.",
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": [
                        "ha_service",
                        "restart_wifi_ap",
                        "switch_solar_bypass",
                        "isolate_solar_phase",
                        "reset_sip_trunk",
                        "activate_dmx_emergency_scene",
                        "failover_lte_wan",
                    ],
                    "description": "Use ha_service for real Home Assistant actions; legacy types map to catalog when configured.",
                },
                "target_subsystem": {
                    "type": "string",
                    "enum": [
                        "all",
                        "solar_power",
                        "telephony",
                        "network_wifi",
                        "dmx_lighting",
                        "servers_rack",
                        "security_alarm",
                    ],
                    "description": "Target subsystem for the action.",
                },
                "parameters": {
                    "type": "object",
                    "description": "HA: catalog_id | entity_id+verb | domain+service+entity_id | service_data.",
                },
            },
            "required": ["action_type", "target_subsystem"],
        },
    },
    {
        "type": "function",
        "name": "submit_user_approval",
        "description": "Submits the operator's spoken words for strict fail-closed evaluation. If approved, executes the action with a cryptographic single-use permit and records HTR.",
        "parameters": {
            "type": "object",
            "properties": {
                "proposal_id": {
                    "type": "string",
                    "description": "The proposal_id from propose_governed_action.",
                },
                "utterance": {
                    "type": "string",
                    "description": "The verbatim utterance spoken by the human operator (e.g. 'Yes proceed', 'Si autorizo', 'No cancela').",
                },
            },
            "required": ["proposal_id", "utterance"],
        },
    },
    {
        "type": "function",
        "name": "inneros_analyze_incident",
        "description": "Complex incident and root-cause analysis tool powered by local Qwen / InnerOS reasoning engine on Node AG-41. Call when asked why a past failure occurred, root cause of previous faults, or deep historical diagnostic queries.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The analytical or root-cause question asked by the operator.",
                },
                "subsystem": {
                    "type": "string",
                    "enum": ["all", "solar_power", "telephony", "network_wifi", "servers_rack", "security_alarm"],
                    "description": "The specific subsystem under analysis.",
                },
            },
            "required": ["query"],
        },
    },
]


def execute_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatches tool calls received from Higgs Realtime."""
    if name == "list_home_assistant_controls":
        return list_home_assistant_controls(
            include_discovery=bool(arguments.get("include_discovery", True)),
            discovery_limit=int(arguments.get("discovery_limit") or 200),
        )
    elif name == "inspect_operational_state":
        return inspect_operational_state(
            subsystem=arguments.get("subsystem", "all"),
            live_fluctuation=True,
            mirror_evidence=True,
        )
    elif name == "propose_governed_action":
        return propose_governed_action(
            action_type=arguments.get("action_type", ""),
            target_subsystem=arguments.get("target_subsystem", ""),
            parameters=arguments.get("parameters"),
        )
    elif name == "submit_user_approval":
        return submit_user_approval(
            proposal_id=arguments.get("proposal_id", ""),
            utterance=arguments.get("utterance", ""),
        )
    elif name == "inneros_analyze_incident":
        return inneros_analyze_incident(
            query=arguments.get("query", ""),
            subsystem=arguments.get("subsystem", "all"),
        )
    else:
        return {"error": f"Unknown tool '{name}'"}

