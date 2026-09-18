from __future__ import annotations
import hmac, json, os, secrets, threading, time
from pathlib import Path
from urllib.parse import parse_qs

_LOCK=threading.Lock()
_DIRECTORY=Path.home()/'.local/state/inneros-voiceops-boson'


def restore_provider_settings():
    path=_DIRECTORY/'provider_settings.json'
    try:
        values=json.loads(path.read_text())
        for name in ('BOSON_API_KEY',):
            if isinstance(values.get(name),str) and values[name] and not os.getenv(name):
                os.environ[name]=values[name]
    except (OSError,ValueError):pass


def _invitation():
    _DIRECTORY.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=_DIRECTORY/'operator_invitation.json'
    try:
        invite=json.loads(path.read_text())
        if invite.get('expires_at',0)>time.time():return invite
    except (OSError,ValueError):pass
    invite={'id':secrets.token_urlsafe(32),'expires_at':time.time()+3600}
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(invite,f)
    return invite


def route_get(handler):
    if handler.path=='/api/operator/setup-link':
        if handler.client_address[0] not in ('127.0.0.1','::1','192.168.1.4') or handler.headers.get('CF-Connecting-IP') or handler.headers.get('X-Forwarded-For'):
            handler._send_json({'error':'Operator setup link is only available on the local server'},status=403)
            return True
        with _LOCK:invite=_invitation()
        handler._send_json({'setup_url':'https://voiceopsboson.creatorcore.ai/setup/'+invite['id'],'expires_at':invite['expires_at']})
        return True
    if not handler.path.startswith('/setup/'):return False
    supplied=handler.path.split('?',1)[0].removeprefix('/setup/')
    with _LOCK:invite=_invitation()
    if not hmac.compare_digest(supplied,invite['id']):
        handler._send_json({'error':'Setup link is invalid or expired'},status=403);return True
    _page(handler,'''<h1>Activar Boson Higgs</h1><p>El panel local ya funciona. Pega la clave de Boson para activar la conversacion y el audio nativos. La clave se guarda solo en tu servidor, fuera de GitHub.</p><form method="post"><label>Clave de Boson <input type="password" name="boson_key" required autocomplete="off" placeholder="bai-..."></label><button type="submit">Validar y activar Higgs</button></form><p>Una vez validada, vuelve al panel y pulsa Iniciar voz.</p>''')
    return True


def route_post(handler):
    if not handler.path.startswith('/setup/'):return False
    supplied=handler.path.split('?',1)[0].removeprefix('/setup/')
    with _LOCK:invite=_invitation()
    if not hmac.compare_digest(supplied,invite['id']):
        handler._send_json({'error':'Invalid setup invitation'},status=403);return True
    length=int(handler.headers.get('Content-Length','0'))
    if not 0<length<=4096:
        handler._send_json({'error':'Invalid form size'},status=400);return True
    form=parse_qs(handler.rfile.read(length).decode('utf-8'))
    value=(form.get('boson_key') or [''])[0].strip()
    if not value or len(value)>1024:
        handler._send_json({'error':'Invalid credential format'},status=400);return True
    from .adapters.boson_client import mint_client_secret
    with _LOCK:
        old=os.environ.get('BOSON_API_KEY')
        os.environ['BOSON_API_KEY']=value
        result=mint_client_secret(ttl_seconds=30)
        if not result.get('ok'):
            if old is not None:os.environ['BOSON_API_KEY']=old
            else:os.environ.pop('BOSON_API_KEY',None)
            _page(handler,'<h1>No se pudo validar Boson</h1><p>Revisa la clave y los permisos de tu cuenta. No se ha guardado ningun cambio.</p><p><a href="">Intentar de nuevo</a></p>',status=400)
            return True
        path=_DIRECTORY/'provider_settings.json'
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:json.dump({'BOSON_API_KEY':value},f)
        (_DIRECTORY/'operator_invitation.json').unlink(missing_ok=True)
    _page(handler,'<h1>Boson validado y activado</h1><p>La credencial se valido directamente con Boson. Ya puedes abrir el panel e iniciar la voz.</p><p><a href="/">Abrir VoiceOps</a></p>')
    return True


def _page(handler,body,status=200):
    html=('<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>VoiceOps configuracion</title><style>body{font:18px system-ui;max-width:660px;margin:8vh auto;padding:24px;color:#172338}h1{font-size:32px}input{display:block;width:90%;padding:14px;margin:12px 0;font-size:18px}button{padding:14px 24px;font-size:18px;cursor:pointer}p{line-height:1.6}</style>'+body+'</html>').encode()
    handler.send_response(status)
    handler.send_header('Content-Type','text/html; charset=utf-8')
    handler.send_header('Content-Length',str(len(html)))
    handler.send_header('Cache-Control','no-store')
    handler.send_header('Referrer-Policy','no-referrer')
    handler.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
    handler.end_headers();handler.wfile.write(html)
