from __future__ import annotations

import base64
import hashlib
import json
import logging
import struct
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("voiceops.websocket")

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def compute_accept_key(sec_key: str) -> str:
    combined = sec_key.strip() + WS_GUID
    sha = hashlib.sha1(combined.encode("utf-8")).digest()
    return base64.b64encode(sha).decode("utf-8")


def read_ws_frame(rfile) -> tuple[int, bytes] | None:
    """Reads and unmasks a single RFC 6455 WebSocket frame from a socket rfile."""
    head = rfile.read(2)
    if not head or len(head) < 2:
        return None

    byte1, byte2 = head[0], head[1]
    fin = (byte1 & 0x80) != 0
    opcode = byte1 & 0x0F
    masked = (byte2 & 0x80) != 0
    payload_len = byte2 & 0x7F

    if payload_len == 126:
        ext_len = rfile.read(2)
        if len(ext_len) < 2:
            return None
        payload_len = struct.unpack("!H", ext_len)[0]
    elif payload_len == 127:
        ext_len = rfile.read(8)
        if len(ext_len) < 8:
            return None
        payload_len = struct.unpack("!Q", ext_len)[0]

    mask = rfile.read(4) if masked else b""
    payload = rfile.read(payload_len)
    if len(payload) < payload_len:
        return None

    if masked:
        unmasked = bytearray(payload_len)
        for i in range(payload_len):
            unmasked[i] = payload[i] ^ mask[i % 4]
        payload = bytes(unmasked)

    return opcode, payload


def encode_ws_frame(opcode: int, payload: bytes) -> bytes:
    """Encodes a payload into an unmasked server-to-client RFC 6455 WebSocket frame."""
    payload_len = len(payload)
    first_byte = 0x80 | (opcode & 0x0F)

    if payload_len <= 125:
        header = bytes([first_byte, payload_len])
    elif payload_len <= 65535:
        header = bytes([first_byte, 126]) + struct.pack("!H", payload_len)
    else:
        header = bytes([first_byte, 127]) + struct.pack("!Q", payload_len)

    return header + payload


def generate_pcm16_speech_audio(duration_sec: float = 1.0, freq: float = 220.0, sample_rate: int = 16000) -> bytes:
    """Generates synthetic PCM16 mono audio bytes for realtime streaming demonstration."""
    import math
    num_samples = int(duration_sec * sample_rate)
    samples = []
    for i in range(num_samples):
        t = float(i) / sample_rate
        # Baritone fundamental with soft harmonics for pleasant masculine voice audio
        val = 0.5 * math.sin(2.0 * math.pi * freq * t) + 0.25 * math.sin(2.0 * math.pi * (freq * 1.5) * t)
        # Apply gentle envelope
        env = min(1.0, i / 200.0) * min(1.0, (num_samples - i) / 200.0)
        sample_int = int(val * env * 16000)
        samples.append(max(-32768, min(32767, sample_int)))
    return struct.pack(f"<{len(samples)}h", *samples)
