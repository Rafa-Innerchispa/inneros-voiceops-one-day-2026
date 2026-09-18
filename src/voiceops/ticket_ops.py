from __future__ import annotations
import hashlib, json, os, threading, uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK=threading.Lock()


def execute_approved_ticket(proposal_id,utterance,session_id,registry,gate,permits)->dict[str,Any]:
    with _LOCK:
        proposal=registry.get_proposal(proposal_id)
        if proposal is None:
            return {'status':'BLOCKED','decision':'PROPOSAL_NOT_FOUND','reason':'No active proposal','fail_closed':True}
        decision=gate.decide(utterance)
        if not decision.approved:
            return {'status':'BLOCKED','decision':'REJECTED_OR_AMBIGUOUS','reason':decision.reason,'fail_closed':True}
        if proposal.action_type!='create_incident_ticket':
            return {'status':'BLOCKED','reason':'Physical mutations disabled in public demo. A local incident ticket can be created instead.','fail_closed':True}
        from .live_status import telemetry_snapshot
        snapshot=telemetry_snapshot(proposal.payload.get('target_subsystem','all'))
        binding={'session_id':session_id,'source_event_id':'evt_'+proposal_id,'action_type':proposal.action_type,
                 'approval_transcript':utterance,'proposal':asdict(proposal),'state_snapshot':snapshot}
        permit=permits.issue(**binding)
        allowed,reason,_=permits.consume(permit.permit_id,**binding)
        if not allowed:return {'status':'BLOCKED','reason':reason,'fail_closed':True}
        ticket_id='vo-'+uuid.uuid4().hex[:12]
        entry={'ticket_id':ticket_id,'proposal_id':proposal_id,'action_type':proposal.action_type,
               'created_at':datetime.now(timezone.utc).isoformat(),'permit':permit.safe_dict(),
               'evidence':snapshot,'status':'OPEN','source':'VoiceOps approved local action'}
        raw=json.dumps(entry,sort_keys=True,ensure_ascii=False).encode()
        directory=Path(os.getenv('VOICEOPS_STATE_DIR',str(Path.home()/'.local/state/inneros-voiceops-boson')))
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        path=directory/(ticket_id+'.json')
        try:
            with path.open('xb') as handle:handle.write(raw);handle.flush();os.fsync(handle.fileno())
            checked=path.read_bytes()
            if checked!=raw:raise RuntimeError('Ticket verification failed')
        except Exception as exc:
            return {'status':'FAILED','reason':type(exc).__name__,'permit_id':permit.permit_id}
        registry._active_proposals.pop(proposal_id,None)
        digest=hashlib.sha256(checked).hexdigest()
        result={'status':'EXECUTED','action_id':ticket_id,'action_type':proposal.action_type,'permit_id':permit.permit_id,
                'evidence_sha256':digest,'postcondition_verified':True,'truth':'LIVE',
                'htr_seconds_returned':0,'classification':'NOT_MEASURED',
                'details':{'ticket_id':ticket_id,'persistence':'LOCAL','readback_verified':True,
                  'physical_mutation':False,'htr_metric':{'saved_seconds':0,'classification':'NOT_MEASURED'}},
                'message':'Incident ticket created and independently read back on the local server. No physical equipment was changed.'}
        # Optional mirror must never block the operational path.
        def mirror():
            try:
                from .adapters.insforge_provider import InsForgeProvider
                InsForgeProvider().append_event(session_id,'governed_action_verified',result)
            except Exception:pass
        threading.Thread(target=mirror,daemon=True).start()
        return result
