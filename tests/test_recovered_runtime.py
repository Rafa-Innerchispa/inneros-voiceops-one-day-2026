"""Regression checks for recovered local runtime. These tests never actuate hardware."""
from __future__ import annotations
import json
from pathlib import Path
from types import SimpleNamespace
import pytest


def test_boson_configuration_uses_ga_audio_contract():
    from voiceops.adapters.boson_client import build_session_update
    message=build_session_update()
    assert message['type']=='session.update'
    assert message['session']['model']=='higgs-realtime'
    assert message['session']['output_modalities']==['audio']
    assert message['session']['audio']['input']['transcription']['model']=='higgs-stt-3.1'
    assert 'whisper-1' not in json.dumps(message)


def test_missing_boson_key_never_mints_a_local_fake(monkeypatch):
    from voiceops.adapters.boson_client import mint_client_secret
    monkeypatch.delenv('BOSON_API_KEY',raising=False)
    monkeypatch.delenv('HIGGS_API_KEY',raising=False)
    output=mint_client_secret()
    assert output['ok'] is False
    assert not output.get('token')


def test_browser_queue_is_24k_sequential_and_does_not_cancel_from_waveform():
    from voiceops.webapp import VoiceOpsHandler
    source=Path(__import__('voiceops').__file__).with_name('web').joinpath('app.js').read_text()
    implementation=source[source.index('// Recovery transport:'):]
    assert 'nextPlayAt = begin + buffer.duration' in implementation
    assert "function(data, rate = 24000)" in implementation
    waveform=implementation[implementation.index('initWaveform = function()'):implementation.index('const oldVoiceStatus=')]
    assert 'triggerInstantBargeIn' not in waveform
    assert "type:'response.cancel'" in implementation
    assert 'Test audio' in implementation


def test_static_html_does_not_publish_old_fake_values():
    source=Path(__import__('voiceops').__file__).with_name('web').joinpath('index.html').read_text()
    assert '52.4V' not in source
    assert '18.0% Packet Loss' not in source
    assert '4 Registered (100, 101, 102, 103)' not in source
    assert 'PV Generation:' not in source


@pytest.mark.parametrize('utterance',['Si, autorizo crear el ticket ahora.','Yes, authorize and proceed.'])
def test_ticket_is_real_local_persistence_and_single_use(tmp_path,monkeypatch,utterance):
    from voiceops import governed_tools,live_status
    monkeypatch.setenv('VOICEOPS_STATE_DIR',str(tmp_path))
    monkeypatch.setattr(live_status,'telemetry_snapshot',lambda *a:{'truth':'SYNTHETIC','test_fixture':True})
    proposal=governed_tools.propose_governed_action('create_incident_ticket','all')
    output=governed_tools.submit_user_approval(proposal['proposal_id'],utterance,'fixture-session')
    assert output['status']=='EXECUTED'
    assert output['postcondition_verified'] is True
    assert output['details']['physical_mutation'] is False
    assert output['htr_seconds_returned']==0
    files=list(tmp_path.glob('vo-*.json'))
    assert len(files)==1
    stored=json.loads(files[0].read_text())
    assert stored['ticket_id']==output['action_id']
    repeat=governed_tools.submit_user_approval(proposal['proposal_id'],utterance,'fixture-session')
    assert repeat['status']=='BLOCKED'
    assert len(list(tmp_path.glob('vo-*.json')))==1


def test_physical_mutation_is_blocked_even_with_yes():
    from voiceops.governed_tools import propose_governed_action,submit_user_approval
    proposal=propose_governed_action('restart_wifi_ap','network_wifi')
    output=submit_user_approval(proposal['proposal_id'],'Yes, authorize and proceed.')
    assert output['status']=='BLOCKED'
    assert output['fail_closed'] is True


def test_ambiguous_human_approval_is_blocked():
    from voiceops.governed_tools import propose_governed_action,submit_user_approval
    proposal=propose_governed_action('create_incident_ticket','all')
    output=submit_user_approval(proposal['proposal_id'],'Maybe later, not sure')
    assert output['status']=='BLOCKED'


def test_standalone_higgs_tool_cannot_fabricate_human_approval():
    from voiceops.adapters.boson_client import handle_tool_call_event
    result=handle_tool_call_event({'type':'response.function_call_arguments.done','name':'submit_user_approval','call_id':'fixture', 'arguments':json.dumps({'proposal_id':'anything','utterance':'Yes authorize'})})
    assert result['record']['output']['status']=='BLOCKED'


def test_local_qwen_path_makes_a_real_adapter_request(monkeypatch):
    from voiceops import local_dialogue
    calls=[]
    class Reasoner:
        def __init__(self, **kwargs): pass
        model='fixture-local-model';endpoint='http://localhost/fixture';timeout_seconds=1
        def _post_json(self,endpoint,payload,timeout):
            calls.append(payload)
            return {'choices':[{'message':{'content':json.dumps({'reply':'A measured test answer'})}}]}
    monkeypatch.setattr(local_dialogue,'LocalAMDReasoner',Reasoner)
    result=local_dialogue.converse('Hola','fixture-qwen-call')
    assert len(calls)==1
    assert result['reply']=='A measured test answer'
    assert result['route']['truth']=='LIVE_MODEL_RESPONSE'
    assert not result['tool_records']


def test_operator_setup_url_not_exposed_to_public_proxy():
    from voiceops.operator_setup import route_get
    results=[]
    handler=SimpleNamespace(path='/api/operator/setup-link',client_address=('192.168.1.4',1),headers={'CF-Connecting-IP':'203.0.113.10'},_send_json=lambda payload,**kw:results.append((payload,kw)))
    assert route_get(handler) is True
    assert results[0][1]['status']==403


def test_unlinked_partners_are_not_claimed_active():
    from voiceops.live_status import status_snapshot
    result=status_snapshot()
    assert result['providers']['insforge']['mode']=='NOT_CONNECTED'
    assert result['providers']['instacloud']['mode']=='NOT_CONNECTED'
