from __future__ import annotations
import json, threading, time
from typing import Any
from .adapters.local_amd import LocalAMDReasoner, _extract_content

_sessions:dict[str,list[dict[str,str]]]={}
_lock=threading.Lock()
_LAST_RESPONSE:float|None=None


def converse(text:str,session_id:str='local-browser',active_proposal_id:str|None=None)->dict[str,Any]:
    global _LAST_RESPONSE
    if not text.strip():return {'reply':'Escribe o di tu pregunta.','audio_source':'BROWSER_TTS_FALLBACK'}
    from .governed_tools import execute_tool_call
    reasoner=LocalAMDReasoner(timeout_seconds=18)
    system='''Eres Ralphi, un asistente operativo real de InnerOS en Guayaquil. Rafael esta en San Francisco. Conversa con naturalidad en el idioma del usuario; un saludo no necesita consultar sensores. Eres el modelo LOCAL Qwen y esta ruta usa voz alternativa del navegador, NO eres Higgs.
Devuelve JSON con UNA de estas dos formas: {"reply":"respuesta breve"} o {"tool":"nombre","arguments":{...}}.
Herramientas permitidas: inspect_operational_state(subsystem: all|solar_power|network_wifi|security_alarm|telephony|video_surveillance|servers_rack), propose_governed_action(action_type:create_incident_ticket,target_subsystem:all,parameters:{}), submit_user_approval(proposal_id,utterance), inneros_analyze_incident(query,subsystem).
No inventes hechos de la casa ni estados de integraciones. Consulta herramientas para valores actuales. Potencia AC de salida del inversor NO es generacion solar. Los datos UNVERIFIED, STALE y NOT_CONNECTED no son mediciones disponibles. No deduzcas una causa historica sin registros. Para actuar solo puedes crear un ticket local despues de proponerlo y recibir autorizacion explicita humana. No puedes reiniciar red, cortar energia, desarmar alarmas o llamar al telefono. Nunca digas que una accion bloqueada se ejecuto. Responde en 1-3 frases.'''
    with _lock:history=list(_sessions.get(session_id,[]))[-12:]
    messages=[{'role':'system','content':system},*history,{'role':'user','content':text[:1000]}]
    if active_proposal_id:messages[0]['content']+=' Propuesta actualmente pendiente: '+active_proposal_id
    records=[];proposal=None;approval=None
    try:
        for _ in range(4):
            payload={'model':reasoner.model,'messages':messages,'temperature':0.2,'max_tokens':400,
                     'response_format':{'type':'json_object'}}
            raw=reasoner._post_json(reasoner.endpoint,payload,reasoner.timeout_seconds)
            content=_extract_content(raw)
            clean=content.strip()
            if clean.startswith('```'):clean='\n'.join(clean.splitlines()[1:-1])
            try:result=json.loads(clean)
            except ValueError:result={'reply':content}
            _LAST_RESPONSE=time.time()
            if result.get('reply'):
                reply=str(result['reply'])
                with _lock:
                    if len(_sessions)>100:_sessions.clear()
                    _sessions[session_id]=[*history,{'role':'user','content':text},{'role':'assistant','content':reply}][-14:]
                return {'reply':reply,'tool_records':records,'proposal':proposal,'approval_result':approval,
                        'model':reasoner.model,'route':{'truth':'LIVE_MODEL_RESPONSE','provider':'local-amd-5'},
                        'AUDIO_SOURCE':'BROWSER_TTS_FALLBACK'}
            name=str(result.get('tool',''));args=result.get('arguments') or {}
            if name not in {'inspect_operational_state','propose_governed_action','submit_user_approval','inneros_analyze_incident'} or not isinstance(args,dict):
                raise ValueError('Invalid model tool request')
            if name=='submit_user_approval':args['utterance']=text;args['session_id']=session_id
            t=time.monotonic();output=execute_tool_call(name,args)
            records.append({'tool_name':name,'arguments':args,'output':output,'duration_ms':round((time.monotonic()-t)*1000)})
            if name=='propose_governed_action':proposal=output
            if name=='submit_user_approval':approval=output
            messages.extend([{'role':'assistant','content':content},{'role':'user','content':'Resultado verificado de herramienta: '+json.dumps(output,ensure_ascii=False)}])
        return {'reply':'La consulta se realizo. El detalle verificado esta en el panel de herramientas.','tool_records':records,'proposal':proposal,'approval_result':approval}
    except Exception as exc:
        return {'reply':'El modelo local no pudo completar esta respuesta. Los estados disponibles siguen visibles en el panel.',
                'error':type(exc).__name__,'tool_records':records,'route':{'truth':'OFFLINE','provider':'local-amd-5'},'AUDIO_SOURCE':'BROWSER_TTS_FALLBACK'}
