from __future__ import annotations
import copy, json, os, socket, subprocess, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from typing import Any

_lock=threading.Lock()
_cache:dict[str,Any]={}
_cache_at=0.0
_boot=time.time()
_sha='unknown'
try:
 _sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parents[2],text=True,timeout=3).strip()
except Exception:pass


def build_identity():
 return {'build_sha':_sha,'runtime':'local-primary','uptime_seconds':round(time.time()-_boot),
         'voice_transport':'boson-server-relay','production_writes':False, 'allowed_local_actions':['create_incident_ticket']}


def _pbx():
 from .governed_tools import get_operational_registry
 from .adapters.home_assistant_provider import freshness_seconds
 now=datetime.now(timezone.utc).isoformat()
 if os.getenv('VOICEOPS_LOCAL_HOME','').lower()=='true':
  try:
   # Reuse the authenticated existing runtime; no PBX secrets leave its broker.
   with urlopen('http://127.0.0.1:8796/v1/telephony/status',timeout=10) as response:raw=json.load(response)
   endpoints=raw.get('owner_endpoints') or []
   verified=bool(endpoints) and all(not str(v.get('status','')).startswith('StatusError') for v in endpoints)
   peers=[{'ext':str(v.get('extension','')),'registered':bool(v.get('registered')),
           'status':str(v.get('status','UNKNOWN')),'source':v.get('source','ucm_runtime')} for v in endpoints]
   return {'truth':'LIVE' if verified else 'UNVERIFIED','source_provider':'Existing VoiceOps UCM live status broker',
     'observed_at':now if verified else None,'scope':'Configured owner extensions only, not PBX-wide inventory',
     'registered_extensions':[v for v in peers if v['registered']], 'peers':peers,
     'status':'CONNECTED' if verified else 'UNVERIFIED','hardware':'Grandstream UCM6104','sip_bind':'SIP / UCM local integration'}
  except Exception as exc:
   return {'truth':'OFFLINE','source_provider':'Existing VoiceOps UCM status broker','observed_at':None,
           'status':'OFFLINE','registered_extensions':[], 'error':type(exc).__name__}
 result=get_operational_registry()._read_ami_extensions()
 result['registered_extensions']=[v for v in result.get('registered_extensions',[]) if v.get('status')=='ONLINE']
 result['hardware']='Grandstream UCM6104'
 result['status']='CONNECTED' if result.get('truth')=='LIVE' else result.get('truth','UNVERIFIED')
 result.setdefault('hardware','Grandstream UCM6104')
 return result


def _servers():
 now=datetime.now(timezone.utc).isoformat()
 try:
  mem={line.split(':')[0]:int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if len(line.split())>=2}
  return {'truth':'LIVE','source_provider':'Local operating system /proc, primary host', 'observed_at':now,
    'status':'OBSERVED','cpu_load_avg':list(os.getloadavg()),
    'memory_total_gb':round(mem['MemTotal']/1048576,2),
    'memory_used_gb':round((mem['MemTotal']-mem['MemAvailable'])/1048576,2),
    'node':'primary Intel host; not the AMD inference node'}
 except Exception as exc:return {'truth':'UNVERIFIED','status':'UNVERIFIED','observed_at':None,'error':type(exc).__name__}


def _dmx():
 try:
  if os.getenv('VOICEOPS_LOCAL_HOME','').lower()!='true':raise RuntimeError('Not configured')
  from inneros_core_runtime.agents.ag59_dmx_artnet_orchestrator import dmx_status
  status=dmx_status()
  return {'truth':'LIVE' if status.get('ok') else 'OFFLINE','status':status.get('status','UNVERIFIED'),
   'source_provider':'InnerOS local DMX engine, read-only','observed_at':datetime.now(timezone.utc).isoformat() if status.get('ok') else None,
   'active_scene':status.get('current_scene'), 'running':status.get('running')}
 except Exception as exc:return {'truth':'UNVERIFIED','status':'NOT_CONNECTED','observed_at':None,'error':type(exc).__name__}


def telemetry_snapshot(subsystem='all'):
 global _cache,_cache_at
 from .adapters.home_assistant_provider import read_solar_telemetry,read_alarm_telemetry,read_network_telemetry,read_camera_telemetry,freshness_seconds
 with _lock:
  if time.monotonic()-_cache_at>3:
   operations={'solar_power':read_solar_telemetry,'security_alarm':read_alarm_telemetry,
      'network_wifi':read_network_telemetry,'video_surveillance':read_camera_telemetry,'telephony':_pbx,'servers_rack':_servers,'dmx_lighting':_dmx}
   with ThreadPoolExecutor(max_workers=6) as pool:
    jobs={k:pool.submit(fn) for k,fn in operations.items()}; data={}
    for key,future in jobs.items():
     try:data[key]=future.result(timeout=12)
     except Exception as exc:data[key]={'truth':'UNVERIFIED','status':'UNVERIFIED','error':type(exc).__name__}
   data['instacloud']={'truth':'NOT_CONNECTED','status':'NOT_CONNECTED','observed_at':None,'source_provider':'InstaCloud optional preview'}
   for key,value in data.items():
    value['subsystem']=key; value['freshness_seconds']=freshness_seconds(value.get('observed_at'))
    value.pop('reads',None);value.pop('device_id',None)
    if key=='solar_power':value['inverter_model']='Xmart 24V inverter';value['power_measurement']='AC inverter output, not solar generation'
    if key=='security_alarm':value['status']=str(value.get('arm_mode') or 'UNVERIFIED').upper()
    if key=='video_surveillance':value['status']='PRESENCE_ONLY';value['stream_status']='UNVERIFIED';value['motion_status']='UNVERIFIED'
   _cache=data;_cache_at=time.monotonic()
  data=copy.deepcopy(_cache)
 now=datetime.now(timezone.utc).isoformat()
 if subsystem in data:
  item=data[subsystem]
  return {'site':'Guayaquil Operations Hub (GYE-Node-01)','country':'Ecuador (EC)','query_timestamp':now,'subsystem':subsystem,'truth':item.get('truth'),
    'source_provider':item.get('source_provider'),'observed_at':item.get('observed_at'),'status':item.get('status'),'data':item}
 return {'site':'Guayaquil Operations Hub (GYE-Node-01)','country':'Ecuador (EC)','query_timestamp':now,'subsystem':'all','subsystems':data,
   'active_alerts':[key+': '+str(value.get('truth')) for key,value in data.items() if value.get('truth')!='LIVE']}


def status_snapshot():
 from .adapters.boson_client import connection_status
 state=connection_status()
 with _lock:data=copy.deepcopy(_cache)
 providers={}
 for key,label in [('home_assistant','solar_power'),('grandstream_ami','telephony')]:
  item=data.get(label,{})
  providers[key]={'mode':'REAL' if item.get('truth')=='LIVE' else 'NOT_CONNECTED',
                  'truth':item.get('truth','UNVERIFIED'),'source':item.get('source_provider')}
 providers['boson_higgs']={'mode':'REAL' if state.get('last_audio_at') else 'CONFIGURED' if state.get('configured') else 'NOT_CONNECTED',
                         'connection':state.get('status'),'last_audio_at':state.get('last_audio_at')}
 providers['browser_tts']={'mode':'FALLBACK','note':'Availability is determined by the browser, not this endpoint'}
 providers['qwen_amd']={'mode':'CONFIGURED' if os.getenv('VOICEOPS_AMD5_URL') else 'NOT_CONNECTED','note':'Live model response reported per analysis'}
 providers['insforge']={'mode':'NOT_CONNECTED','note':'Remote authentication/readback not yet verified'}
 providers['instacloud']={'mode':'NOT_CONNECTED','note':'Optional cloud preview not deployed; canonical runtime stays local'}
 return {'AUDIO_SOURCE':'NONE','STT_SOURCE':'SESSION_NEGOTIATED','providers':providers,**build_identity()}
