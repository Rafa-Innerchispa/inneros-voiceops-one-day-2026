from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger('voiceops.boson_client')
BOSON_API_BASE = 'https://api.boson.ai/v1'
BOSON_REALTIME_WS = 'wss://api.boson.ai/v1/realtime'
DEFAULT_MODEL = 'higgs-realtime'
DEFAULT_INSTRUCTIONS = '''You are Ralphi, the InnerOS VoiceOps assistant. Rafael is in San Francisco and his infrastructure is in Guayaquil, Ecuador. Converse naturally in the user's language, Spanish or English, and remember the conversation. A greeting needs a friendly greeting, not a telemetry report. Keep spoken answers to two or three sentences unless asked for details.
For current operational facts ALWAYS use inspect_operational_state. Treat unknown, unavailable, stale and unverified data honestly. Never invent a value, camera image, registered phone, completed action or historic cause. Inverter AC output power is NOT solar PV generation. Battery percent is the inverter's estimate, not a precision state of charge.
For deeper explanation use inneros_analyze_incident, a local Qwen model. Historical causes must be framed as hypotheses unless supported by timestamped evidence. No provider description is evidence of successful integration.
Use propose_governed_action before any action. Request explicit human approval. submit_user_approval is evaluated by a deterministic server gate against the actual user's latest words, never words you invented. You cannot approve your own proposal. Only the allowlisted safe demo action can run; networking, power breakers, alarms and PBX changes are blocked in this demo. A blocked operation is NOT executed. Never claim a simulated action happened physically.
If interrupted, stop speaking and respond to the new request.'''
_LAST_PROBE = {'status': 'NOT_TESTED', 'connected_at': None, 'last_audio_at': None}


def get_boson_api_key() -> str:
    return (os.getenv('BOSON_API_KEY') or os.getenv('HIGGS_API_KEY') or '').strip()


def boson_configured() -> bool:
    return bool(get_boson_api_key())


def connection_status() -> dict[str, Any]:
    return dict(_LAST_PROBE, configured=boson_configured())


def mint_client_secret(*, ttl_seconds: int = 600) -> dict[str, Any]:
    key = get_boson_api_key()
    if not key:
        return {'ok': False, 'error': 'BOSON_API_KEY not configured', 'status': 'NOT_CONNECTED'}
    req = Request(BOSON_API_BASE + '/realtime/client_secrets',
        data=json.dumps({'expires_after': {'seconds': max(10, min(ttl_seconds, 7200))}}).encode(),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(req, timeout=10) as response:
            payload = json.load(response)
        value = payload.get('value') or payload.get('client_secret', {}).get('value')
        if not value:
            return {'ok': False, 'error': 'Boson response did not include a client secret'}
        return {'ok': True, 'token': value, 'ws_url': BOSON_REALTIME_WS,
                'expires_in_seconds': max(0, int(payload.get('expires_at', time.time()+600)-time.time())),
                'model': DEFAULT_MODEL, 'connection_mode': 'direct', 'sample_rate': 24000,
                'subprotocol_prefix': 'bai-client-secret.', 'ready': True,
                'AUDIO_SOURCE': 'NONE', 'provider': 'Boson Higgs Realtime'}
    except HTTPError as exc:
        return {'ok': False, 'error': 'Boson authentication HTTP ' + str(exc.code), 'status': 'NOT_CONNECTED'}
    except (URLError, TimeoutError, ValueError) as exc:
        return {'ok': False, 'error': type(exc).__name__, 'status': 'UNREACHABLE'}


def build_session_update(*, instructions: str | None = None) -> dict[str, Any]:
    from ..governed_tools import HIGGS_TOOL_DEFINITIONS
    return {'type': 'session.update', 'session': {
        'type': 'realtime', 'model': DEFAULT_MODEL, 'max_output_tokens': 600, 'instructions': instructions or DEFAULT_INSTRUCTIONS,
        'output_modalities': ['audio'],
        'audio': {'input': {'format': {'type': 'audio/pcm', 'rate': 24000}, 'noise_reduction': {'type': 'near_field'}, 'turn_detection': {'type': 'server_vad', 'threshold': 0.45, 'silence_duration_ms': 600},
                            'transcription': {'model': 'higgs-stt-3.1'}},
                  'output': {'voice': 'default', 'format': {'type': 'audio/pcm', 'rate': 24000}}},
        'tools': HIGGS_TOOL_DEFINITIONS, 'tool_choice': 'auto'}}


def handle_tool_call_event(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get('type') != 'response.function_call_arguments.done':
        return None
    from ..governed_tools import execute_tool_call
    name = str(event.get('name', ''))
    raw = event.get('arguments', '{}')
    try:
        args = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (ValueError, TypeError):
        args = {}
    # The session relay below binds approval to actual user input. This standalone helper is read-only.
    if name == 'submit_user_approval':
        output = {'status': 'BLOCKED', 'reason': 'Live approval requires an authenticated conversation session'}
    else:
        output = execute_tool_call(name, args)
    call_id = event.get('call_id', str(uuid.uuid4()))
    return {'tool_output_event': {'type': 'conversation.item.create', 'item': {
        'type': 'function_call_output', 'call_id': call_id, 'output': json.dumps(output, ensure_ascii=False)}},
        'response_create_event': {'type': 'response.create'},
        'record': {'tool_name': name, 'arguments': args, 'output': output}}


def relay_boson_websocket(browser_send: Callable[[bytes], None], browser_recv: Callable[[], bytes | None], *, use_ephemeral: str | None = None) -> None:
    import websocket
    from ..governed_tools import execute_tool_call
    key = get_boson_api_key()
    if not key and not use_ephemeral:
        raise RuntimeError('Boson credential unavailable')
    options = {'timeout': 12}
    if use_ephemeral:
        options['subprotocols'] = ['realtime', 'bai-client-secret.' + use_ephemeral]
    else:
        options['header'] = ['Authorization: Bearer ' + key]
    upstream = websocket.create_connection(BOSON_REALTIME_WS, **options)
    upstream.settimeout(1)
    _LAST_PROBE.update(status='CONNECTED', connected_at=time.time())
    stop = threading.Event()
    send_lock = threading.Lock()
    session = {'id': 'boson-' + uuid.uuid4().hex, 'user_text': '', 'active_response': False}
    completed_calls: set[str] = set()
    pending_calls: dict[str, dict[str, Any]] = {}

    def send(event: dict[str, Any]) -> None:
        with send_lock:
            upstream.send(json.dumps(event, ensure_ascii=False))

    def to_browser(event: dict[str, Any]) -> None:
        browser_send(json.dumps(event, ensure_ascii=False).encode())

    def reader() -> None:
        try:
            while not stop.is_set():
                try:
                    raw = upstream.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not raw:
                    break
                event = json.loads(raw)
                kind = event.get('type', '')
                if kind == 'session.created':
                    session['id'] = event.get('session', {}).get('id', session['id'])
                    send(build_session_update())
                if kind == 'response.created':
                    session['active_response'] = True
                if kind in ('conversation.item.input_audio_transcription.completed', 'conversation.item.input_audio_transcription.done'):
                    session['user_text'] = str(event.get('transcript') or event.get('text') or '')
                if kind in ('response.output_audio.delta', 'response.audio.delta') and event.get('delta'):
                    _LAST_PROBE['last_audio_at'] = time.time()
                if kind == 'response.function_call_arguments.done':
                    pending_calls[event.get('call_id', '')] = event
                to_browser(event)
                if kind == 'response.done':
                    session['active_response'] = False
                    response = event.get('response', {})
                    if response.get('status') in ('cancelled', 'failed'):
                        pending_calls.clear()
                        continue
                    calls = [v for v in response.get('output', []) if v.get('type') == 'function_call']
                    if not calls:
                        calls = list(pending_calls.values())
                    pending_calls.clear()
                    count = 0
                    for call in calls:
                        call_id = str(call.get('call_id') or '')
                        if not call_id or call_id in completed_calls:
                            continue
                        completed_calls.add(call_id)
                        name = str(call.get('name', ''))
                        try:
                            args = json.loads(call.get('arguments') or '{}')
                            if not isinstance(args, dict):
                                raise ValueError('Invalid tool arguments')
                            if name == 'submit_user_approval':
                                args['utterance'] = session['user_text']
                                args['session_id'] = session['id']
                            started = time.monotonic()
                            output = execute_tool_call(name, args)
                            duration = round((time.monotonic() - started) * 1000)
                        except Exception as exc:
                            args = {}
                            output = {'status': 'BLOCKED', 'error': type(exc).__name__}
                            duration = 0
                        to_browser({'type': 'voiceops.tool', 'name': name, 'arguments': args,
                                    'output': output, 'duration_ms': duration})
                        send({'type': 'conversation.item.create', 'item': {'type': 'function_call_output',
                            'call_id': call_id, 'output': json.dumps(output, ensure_ascii=False)}})
                        count += 1
                    if count:
                        send({'type': 'response.create'})
        except Exception as exc:
            try:
                to_browser({'type': 'voiceops.transport_error', 'error': type(exc).__name__, 'fallback': True})
            except Exception:
                pass
        finally:
            stop.set()

    # Boson starts a session after the first session.update; do not wait for its acknowledgement.
    send(build_session_update())
    worker = threading.Thread(target=reader, daemon=True)
    worker.start()
    try:
        while not stop.is_set():
            raw = browser_recv()
            if raw is None:
                break
            if not raw:
                continue
            msg = json.loads(raw)
            kind = msg.get('type')
            if kind == 'input_audio_buffer.speech_started' or kind == 'session.update':
                continue  # Server events/configuration are never accepted from the browser.
            if kind == 'response.cancel':
                if session['active_response']:
                    send({'type': 'response.cancel'})
                continue
            if kind not in {'input_audio_buffer.append', 'input_audio_buffer.commit', 'input_audio_buffer.clear', 'conversation.item.create', 'response.create'}:
                continue
            if kind == 'conversation.item.create':
                item = msg.get('item') or {}
                if item.get('role') != 'user' or item.get('type') != 'message':
                    continue
                texts = [str(v.get('text', '')) for v in item.get('content', []) if v.get('type') == 'input_text']
                session['user_text'] = ' '.join(texts)[:1000]
                msg = {'type': kind, 'item': {'type': 'message', 'role': 'user',
                    'content': [{'type': 'input_text', 'text': session['user_text']}]}}
            send(msg)
    finally:
        stop.set()
        upstream.close()
        worker.join(timeout=2)
