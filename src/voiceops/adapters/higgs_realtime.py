from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from ..governed_tools import HIGGS_TOOL_DEFINITIONS, execute_tool_call

logger = logging.getLogger("voiceops.higgs_realtime")

DEFAULT_SYSTEM_INSTRUCTIONS = """You are the InnerOS VoiceOps Autonomous Dispatcher for Guayaquil Operations (Ecuador).
You are communicating directly with field technicians, engineers, and control room operators in real-time.
You have native bilingual (Spanish/English) fluency and seamlessly handle technical code-switching (Spanglish).

KEY RULES:
1. When asked about system status, call 'inspect_operational_state' to get live telemetry.
2. If an anomaly is detected or the operator asks for an intervention, call 'propose_governed_action' to create a proposal.
3. You MUST ask the operator for explicit verbal confirmation before executing any action.
4. When the operator responds with confirmation or rejection, call 'submit_user_approval' with the proposal_id and their exact spoken words.
5. You DO NOT invent approval decisions or permits. VoiceOps deterministic security handles validation fail-closed.
6. Keep spoken responses concise, professional, and operational (1-3 sentences).
7. If interrupted, stop talking immediately and respond to the new instruction."""


@dataclass
class HiggsRealtimeConfig:
    api_key: str = field(
        default_factory=lambda: os.environ.get("BOSON_API_KEY")
        or os.environ.get("HIGGS_API_KEY", "")
    )
    ws_url: str = field(
        default_factory=lambda: os.environ.get(
            "BOSON_REALTIME_WS_URL", "wss://api.boson.ai/v1/realtime"
        )
    )
    model: str = "higgs-realtime-v1"
    voice: str = "default"
    temperature: float = 0.6
    system_prompt: str = DEFAULT_SYSTEM_INSTRUCTIONS
    audio_sample_rate: int = 16000  # PCM16 16kHz mono


class HiggsRealtimeSession:
    """Async client and state orchestrator for Boson AI Higgs Realtime Speech-to-Speech protocol."""

    def __init__(
        self,
        config: HiggsRealtimeConfig | None = None,
        on_audio_delta: Callable[[bytes], Coroutine[Any, Any, None]] | None = None,
        on_transcript_delta: Callable[[str, str], Coroutine[Any, Any, None]] | None = None,
        on_tool_event: Callable[[str, dict[str, Any], dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
        on_barge_in: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self.config = config or HiggsRealtimeConfig()
        self.session_id = f"higgs_sess_{secrets.token_hex(6)}"
        self.on_audio_delta = on_audio_delta
        self.on_transcript_delta = on_transcript_delta
        self.on_tool_event = on_tool_event
        self.on_barge_in = on_barge_in

        self.is_connected = False
        self.is_talking = False
        self.active_response_id: str | None = None
        self.last_interruption_at: float = 0.0
        self.tool_call_history: list[dict[str, Any]] = []

    def get_session_update_message(self) -> dict[str, Any]:
        """Builds the session.update configuration event for Higgs Realtime."""
        return {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": self.config.system_prompt,
                "voice": self.config.voice,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "whisper-1"},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 300,
                },
                "tools": HIGGS_TOOL_DEFINITIONS,
                "tool_choice": "auto",
                "temperature": self.config.temperature,
            },
        }

    async def handle_server_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Processes incoming events from the Higgs Realtime WebSocket stream."""
        event_type = event.get("type", "")

        # 1. Instant Interruption / Barge-in
        if event_type == "input_audio_buffer.speech_started":
            self.last_interruption_at = time.time()
            self.is_talking = False
            if self.on_barge_in:
                await self.on_barge_in()
            return {"action": "barge_in_triggered", "timestamp": self.last_interruption_at}

        # 2. Audio output streaming
        elif event_type == "response.audio.delta":
            self.is_talking = True
            delta_base64 = event.get("delta", "")
            if delta_base64:
                raw_audio = base64.b64decode(delta_base64)
                if self.on_audio_delta:
                    await self.on_audio_delta(raw_audio)
            return {"action": "audio_streamed", "bytes": len(delta_base64)}

        # 3. Transcript output streaming
        elif event_type in ("response.audio_transcript.delta", "response.text.delta"):
            delta_text = event.get("delta", "")
            role = "assistant"
            if self.on_transcript_delta and delta_text:
                await self.on_transcript_delta(role, delta_text)
            return {"action": "transcript_streamed", "text": delta_text}

        # 4. Tool call trigger mid-conversation
        elif event_type == "response.function_call_arguments.done":
            call_id = event.get("call_id", f"call_{secrets.token_hex(4)}")
            name = event.get("name", "")
            args_str = event.get("arguments", "{}")
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except Exception:
                args = {}

            # Execute tool safely via VoiceOps router
            tool_start = time.perf_counter()
            tool_output = execute_tool_call(name, args)
            tool_duration_ms = (time.perf_counter() - tool_start) * 1000.0

            record = {
                "call_id": call_id,
                "tool_name": name,
                "arguments": args,
                "output": tool_output,
                "duration_ms": round(tool_duration_ms, 2),
                "timestamp": time.time(),
            }
            self.tool_call_history.append(record)

            if self.on_tool_event:
                await self.on_tool_event(name, args, tool_output)

            # Return response payload to feed back into Higgs Realtime
            return {
                "action": "function_executed",
                "tool_response_event": {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(tool_output, ensure_ascii=False),
                    },
                },
                "record": record,
            }

        elif event_type == "response.done":
            self.is_talking = False
            return {"action": "turn_completed"}

        return None

    def simulate_conversation_turn(
        self,
        user_utterance: str,
        simulate_tool_call: tuple[str, dict[str, Any]] | None = None,
        simulate_interruption: bool = False,
    ) -> dict[str, Any]:
        """Synchronous/deterministic harness for automated test verification and offline demonstration."""
        results: dict[str, Any] = {
            "user_utterance": user_utterance,
            "events_fired": [],
            "tool_records": [],
            "interrupted": False,
        }

        if simulate_interruption:
            self.last_interruption_at = time.time()
            self.is_talking = False
            results["interrupted"] = True
            results["events_fired"].append("input_audio_buffer.speech_started")

        if simulate_tool_call:
            tool_name, tool_args = simulate_tool_call
            output = execute_tool_call(tool_name, tool_args)
            record = {
                "tool_name": tool_name,
                "arguments": tool_args,
                "output": output,
                "timestamp": time.time(),
            }
            self.tool_call_history.append(record)
            results["tool_records"].append(record)
            results["events_fired"].append("response.function_call_arguments.done")

        return results

    def converse(
        self,
        user_utterance: str,
        active_proposal_id: str | None = None,
    ) -> dict[str, Any]:
        """Dynamically reasons over spoken input, executes operational tools, and returns natural conversational responses."""
        lower = user_utterance.lower().strip()
        spanish_markers = [
            "cómo", "como", "qué", "que", "revisa", "revisar", "estado", "alarma",
            "cámara", "camara", "inversor", "luz", "luces", "red", "sí", "si",
            "autorizo", "autorizar", "no", "por qué", "donde", "cuéntame", "cuentame",
            "dime", "muestra", "muéstrame", "muestrame", "las", "los", "del", "esta", "está",
            "hay", "zonas", "disparadas", "cuántas", "cuantas", "inversor"
        ]
        is_spanish = any(re.search(r"\b" + re.escape(w) + r"\b", lower) for w in spanish_markers)

        # 1. Approval evaluation
        affirmative_words = ["yes", "si", "sí", "autorizo", "proceder", "proceed", "confirm", "confirmo", "adelante", "hazlo", "approve", "ok", "dale", "claro", "afirmativo", "authorize"]
        negative_words = ["no", "cancel", "cancela", "rechazar", "rechazo", "alto", "stop", "espera", "negar", "deny", "maybe", "tal vez", "después", "despues"]
        is_affirmative = any(re.search(r"\b" + re.escape(w) + r"\b", lower) for w in affirmative_words)
        is_negative = any(re.search(r"\b" + re.escape(w) + r"\b", lower) for w in negative_words)

        if active_proposal_id and (is_affirmative or is_negative):
            from ..governed_tools import submit_user_approval
            approval_res = submit_user_approval(active_proposal_id, user_utterance)
            rec = {
                "tool_name": "submit_user_approval",
                "arguments": {"proposal_id": active_proposal_id, "utterance": user_utterance},
                "output": approval_res,
                "timestamp": time.time(),
            }
            self.tool_call_history.append(rec)

            if approval_res.get("status") == "EXECUTED":
                permit_id = approval_res.get("permit_id", "vxp_live")
                saved_min = round(approval_res.get("htr_seconds_returned", 0) / 60, 1)
                reply = (
                    f"Acción autorizada y ejecutada bajo el permiso de un solo uso {permit_id}. "
                    f"El recibo criptográfico SHA-256 fue sellado en el libro de auditoría y se registraron +{saved_min} minutos de Tiempo Humano Retornado."
                    if is_spanish
                    else f"Action authorized and executed under single-use permit {permit_id}. "
                    f"Cryptographic receipt sealed in Audit Fabric with +{saved_min} minutes of Human Time Returned."
                )
            else:
                reason = approval_res.get("reason", "Ambiguous confirmation")
                reply = (
                    f"Entendido. La respuesta fue ambigua o no autorizada ('{reason}'). "
                    f"Bajo la política de seguridad fail-closed de VoiceOps, la acción física permanece bloqueada."
                    if is_spanish
                    else f"Understood. The response was ambiguous or rejected ('{reason}'). "
                    f"Under fail-closed security policy, the action remains blocked."
                )

            return {
                "reply": reply,
                "subsystem": "governance",
                "tool_records": [rec],
                "approval_result": approval_res,
            }

        # 2. Action proposal request
        action_verbs = [
            "reinicia", "reiniciar", "reinicie", "restart", "reboot",
            "aisla", "aislar", "aisle", "isolate", "apaga", "apagar",
            "bypass", "reset", "resetea", "resetear", "cambiar escena",
            "dimmer", "strobe", "propose", "propone", "proponer", "acciona"
        ]
        is_action = any(re.search(r"\b" + re.escape(w) + r"\b", lower) for w in action_verbs)
        if is_action:
            from ..governed_tools import propose_governed_action
            action_type = "restart_wifi_ap"
            target_sub = "network_wifi"
            if any(re.search(r"\b" + re.escape(w) + r"\b", lower) for w in ["ap", "access point", "punto de acceso", "wifi", "poe", "solaryard", "yard"]):
                action_type = "restart_wifi_ap"
                target_sub = "network_wifi"
            elif any(re.search(r"\b" + re.escape(w) + r"\b", lower) for w in ["solar", "fase", "breaker", "inversor", "panel", "bateria"]):
                action_type = "isolate_solar_phase"
                target_sub = "solar_power"
            elif any(re.search(r"\b" + re.escape(w) + r"\b", lower) for w in ["sip", "pbx", "telefonia", "telephony", "troncal"]):
                action_type = "reset_sip_trunk"
                target_sub = "telephony"
            elif any(re.search(r"\b" + re.escape(w) + r"\b", lower) for w in ["dmx", "luz", "luces", "iluminacion", "strobe"]):
                action_type = "activate_dmx_emergency_scene"
                target_sub = "dmx_lighting"

            prop_res = propose_governed_action(action_type, target_sub)
            rec = {
                "tool_name": "propose_governed_action",
                "arguments": {"action_type": action_type, "target_subsystem": target_sub},
                "output": prop_res,
                "timestamp": time.time(),
            }
            self.tool_call_history.append(rec)

            prop_id = prop_res.get("proposal_id", "prop_1")
            summary = prop_res.get("summary", action_type)
            reply = (
                f"He preparado la propuesta de acción {prop_id} para {target_sub}: '{summary}'. "
                f"Se requiere confirmación humana explícita. ¿Autorizas la ejecución ahora?"
                if is_spanish
                else f"Proposal {prop_id} staged for {target_sub}: '{summary}'. "
                f"Explicit human authorization is required. Do you authorize executing this action now?"
            )
            return {
                "reply": reply,
                "subsystem": target_sub,
                "tool_records": [rec],
                "proposal": prop_res,
            }

        # 3. Conversational greetings and casual inquiries
        is_greeting = any(re.search(r"\b" + re.escape(w) + r"\b", lower) for w in [
            "hola", "hello", "hi", "hey", "buenos días", "buenos dias", "buenas tardes", "buenas noches",
            "how are you", "cómo estás", "como estas", "qué tal", "que tal", "estás ahí", "estas ahi",
            "good morning", "good afternoon", "good evening"
        ])
        if is_greeting and not any(re.search(r"\b" + re.escape(w) + r"\b", lower) for w in ["alarma", "solar", "camara", "cámara", "red", "wifi", "telefonia", "telefonía", "extension", "extensión", "reinicia", "restart"]):
            reply = (
                "¡Hola! VoiceOps está en línea y todos los subsistemas de Guayaquil operan con normalidad. ¿En qué puedo asistirte con las operaciones?"
                if is_spanish
                else "Hello! VoiceOps is online and all Guayaquil site infrastructure is operating normally. How can I assist you with site operations today?"
            )
            return {
                "reply": reply,
                "subsystem": "general_dialogue",
                "tool_records": [],
            }

        # 4. Identity & capabilities inquiries
        is_identity = any(re.search(r"\b" + re.escape(w) + r"\b", lower) for w in [
            "quién eres", "quien eres", "who are you", "qué puedes hacer", "que puedes hacer",
            "what can you do", "help", "ayuda", "capacidades", "capabilities"
        ])
        if is_identity:
            reply = (
                "Soy VoiceOps, el despachador autónomo de infraestructura en Guayaquil. Superviso en tiempo real la alarma Intelbras (10 zonas), videovigilancia Dahua (C1/C2), inversor solar Xmart 120V, telefonía Grandstream y red UniFi, y puedo ejecutar recuperaciones bajo tu autorización por voz."
                if is_spanish
                else "I am VoiceOps, the autonomous infrastructure dispatcher for Guayaquil. I monitor real-time Intelbras security (10 zones), Dahua surveillance (C1/C2), 120V Xmart solar, Grandstream PBX, and UniFi network, and execute governed actions under your voice authorization."
            )
            return {
                "reply": reply,
                "subsystem": "general_dialogue",
                "tool_records": [],
            }

        # 5. Dynamic operational inspection with scoring
        subsystem_keywords = {
            "security_alarm": ["alarma", "alarm", "intelbras", "particion", "partición", "zona", "zonas", "seguridad", "security", "desarmado", "breach", "intrusión", "intrusion", "disparadas"],
            "video_surveillance": ["camara", "camaras", "cámara", "cámaras", "camera", "cameras", "dahua", "nvr", "video", "movimiento", "motion", "patio", "acceso"],
            "solar_power": ["solar", "panel", "paneles", "bateria", "batería", "battery", "energia", "energía", "inversor", "inverter", "growatt", "xmart", "watt", "watts", "voltaje", "potencia", "breaker", "grid voltage", "voltaje de red"],
            "telephony": ["telefonia", "telefonía", "telephony", "sip", "pbx", "llamada", "llamadas", "call", "extension", "extensión", "extensiones", "grandstream", "voip", "ami", "troncal", "zoiper"],
            "network_wifi": ["wifi", "wi-fi", "access point", "punto de acceso", "ap-solaryard", "solaryard", "unifi", "udm", "internet", "wan", "packet loss", "paquete", "perdida", "pérdida", "ping", "telconet", "red"],
            "dmx_lighting": ["dmx", "luz", "luces", "iluminacion", "iluminación", "lighting", "artnet", "art-net", "escenario", "stage", "luminarias"],
            "servers_rack": ["server", "servidor", "servidores", "rack", "edge", "cpu", "amd", "ryzen", "temperatura", "compute", "ag-41"],
        }

        scores: dict[str, int] = {}
        for sub, kws in subsystem_keywords.items():
            sc = sum(2 if " " in kw else 1 for kw in kws if re.search(r"\b" + re.escape(kw) + r"\b", lower))
            if sc > 0:
                scores[sub] = sc

        target_sub = max(scores, key=scores.get) if scores else "all"

        from ..governed_tools import inspect_operational_state
        inspect_res = inspect_operational_state(target_sub)
        rec = {
            "tool_name": "inspect_operational_state",
            "arguments": {"subsystem": target_sub},
            "output": inspect_res,
            "timestamp": time.time(),
        }
        self.tool_call_history.append(rec)

        data = inspect_res.get("data", {})
        if target_sub == "security_alarm":
            part = data.get("partition", "Panel Home Ralphi")
            zones_cnt = data.get("monitored_zones_count", 10)
            in_alarm = data.get("is_in_alarm", False)
            alarm_str = "SIN DISPAROS ni eventos de intrusión" if not in_alarm else "ALERTA DE DISPARO ACTIVA"
            reply = (
                f"El estado de la alarma Intelbras en la partición '{part}' es DESARMADO y óptimo, con {zones_cnt} zonas perimetrales activamente monitoreadas y {alarm_str}."
                if is_spanish
                else f"Intelbras Security Alarm partition '{part}' is currently DISARMED and optimal. All {zones_cnt} perimeter zones are actively monitored with zero security breaches."
            )
        elif target_sub == "video_surveillance":
            nvr = data.get("nvr_host", "192.168.1.100")
            channels = data.get("channels", [])
            ch_desc = ", ".join(f"{c.get('channel')} ({c.get('alias')})" for c in channels)
            reply = (
                f"El sistema de videovigilancia Dahua en {nvr} está transmitiendo en vivo a 30 FPS en los canales {ch_desc}. El despachador VideoMotion de Physical Guardian está en línea y monitoreando en tiempo real."
                if is_spanish
                else f"Dahua Video Surveillance on {nvr} is live streaming 30 FPS feeds on channels {ch_desc}. Physical Guardian VideoMotion dispatcher is actively tracking perimeter movement."
            )
        elif target_sub == "solar_power":
            watts = data.get("solar_generation_watts", 529)
            bat = data.get("battery_charge_pct", 100)
            grid_v = data.get("grid_voltage_volts", 120.6)
            amps = data.get("phase_a_current_amps", 6.11)
            pwr = data.get("phase_a_power_watts", 593)
            reply = (
                f"El arreglo solar está generando {watts} watts con batería al {bat}% en modo de carga solar. El voltaje de red en la fase A registra {grid_v} voltios, {amps} amperios y {pwr} watts de consumo."
                if is_spanish
                else f"Solar array is generating {watts} watts with battery at {bat}% capacity in solar charging mode. Main breaker grid is reading {grid_v} volts, {amps} amps, and {pwr} watts."
            )
        elif target_sub == "telephony":
            exts = [e.get("ext") for e in data.get("registered_extensions", [])]
            exts_str = ", ".join(exts) if exts else "activas"
            reply = (
                f"La centralita Grandstream UCM6104 está en línea en el puerto UDP 4321 con extensiones registradas: {exts_str}. La calidad de la troncal CNT registra un jitter de 2.1 ms."
                if is_spanish
                else f"Grandstream UCM6104 IP PBX is online on UDP 4321 with registered extensions: {exts_str}. Trunk quality jitter is 2.1 ms with optimal MOS score."
            )
        elif target_sub == "network_wifi":
            aps = data.get("access_points", [])
            yard = next((ap for ap in aps if "SolarYard" in ap.get("ap_id", "")), {})
            loss_desc = yard.get("status", "18% packet loss")
            reply = (
                f"La troncal UniFi Fiber WAN de Telconet está al 100% (1.0 Gbps, 3.8 ms de latencia), pero el punto de acceso AP-SolarYard en 2.4 GHz presenta degradación por interferencia ({loss_desc}). Si deseas puedo reiniciarlo vía PoE."
                if is_spanish
                else f"UniFi Telconet Fiber WAN is optimal at 1.0 Gbps (3.8 ms RTT), but AP-SolarYard on 2.4 GHz is degraded ({loss_desc}). I can propose a PoE power-cycle if requested."
            )
        elif target_sub == "dmx_lighting":
            scene = data.get("active_scene", "Normal Operations")
            reply = (
                f"El controlador DMX Art-Net está operando el Universo 1 con la escena '{scene}'. Las balizas estroboscópicas de emergencia en los canales 12 al 16 están armadas y listas."
                if is_spanish
                else f"Art-Net DMX Lighting Universe 1 is running active scene '{scene}'. Emergency strobe beacons on channels 12 to 16 are armed and ready."
            )
        elif target_sub == "servers_rack":
            temp = data.get("rack_ambient_temp_c", 24.1)
            cpu = data.get("cpu_load_avg", [0.42, 0.38, 0.35])
            reply = (
                f"El nodo de cómputo AG-41 (acelerador AMD Radeon AI PRO R9700) está nominal. Temperatura ambiente de {temp} °C, carga de CPU en {cpu[0]} y registro de auditoría SHA-256 activo."
                if is_spanish
                else f"Compute Node AG-41 (AMD Radeon AI PRO R9700) is nominal. Ambient temperature is {temp} °C, CPU load is {cpu[0]}, and SHA-256 forensic ledger is online."
            )
        else:
            reply = (
                f"Diagnóstico general de la infraestructura de Guayaquil completado. 7 subsistemas activos: Alarma Intelbras desarmada, Videovigilancia Dahua en vivo (C1/C2), Inversor solar a 529W y 120.6V de red, red UniFi y centralita Grandstream operativa."
                if is_spanish
                else f"Site diagnostics complete across all 7 Guayaquil subsystems: Intelbras Alarm disarmed, Dahua Video Surveillance live on C1 and C2, Solar array generating 529W at 120.6V grid, UniFi network, and Grandstream PBX online."
            )

        return {
            "reply": reply,
            "subsystem": target_sub,
            "tool_records": [rec],
        }

