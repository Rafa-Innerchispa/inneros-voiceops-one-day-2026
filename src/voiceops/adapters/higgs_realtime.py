from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
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

