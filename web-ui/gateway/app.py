from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from jwt import PyJWKClient

Role = Literal['owner', 'operator', 'viewer']
ROLE_RANK: dict[Role, int] = {'viewer': 10, 'operator': 20, 'owner': 30}

FLEET_API = os.environ.get('LGHS_WEB_FLEET_API', 'http://127.0.0.1:8789').rstrip('/')
TOKEN_FILE = Path(os.environ.get('LGHS_WEB_FLEET_TOKEN_FILE', '/etc/lghs-web/fleet-admin-token.json'))
ROLE_FILE = Path(os.environ.get('LGHS_WEB_ROLE_FILE', '/etc/lghs-web/roles.json'))
CSRF_FILE = Path(os.environ.get('LGHS_WEB_CSRF_FILE', '/etc/lghs-web/csrf.key'))
OPS_SOCKET = Path(os.environ.get('LGHS_WEB_OPS_SOCKET', '/run/lghs-web-ops/socket'))
DIST = Path(os.environ.get('LGHS_WEB_DIST', '/usr/local/share/lghs-web-ui'))
PUBLIC_ORIGIN = os.environ.get('LGHS_WEB_PUBLIC_ORIGIN', 'https://fleet.scenicrouteservers.com').rstrip('/')
CF_TEAM_DOMAIN = os.environ.get('LGHS_WEB_CF_TEAM_DOMAIN', '').rstrip('/')
CF_AUDIENCE = os.environ.get('LGHS_WEB_CF_AUDIENCE', '').strip()
ALLOWED_HOSTS = [x.strip() for x in os.environ.get('LGHS_WEB_ALLOWED_HOSTS', 'fleet.scenicrouteservers.com,127.0.0.1,localhost').split(',') if x.strip()]


@dataclass(frozen=True)
class Identity:
    email: str
    role: Role
    subject: str
    access_token: str


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def admin_token() -> str:
    data = load_json(TOKEN_FILE, {})
    token = str(data.get('admin_token') or '') if isinstance(data, dict) else ''
    if not token:
        raise RuntimeError('Fleet API admin token is unavailable')
    return token


def csrf_secret() -> bytes:
    try:
        value = CSRF_FILE.read_bytes().strip()
    except OSError as exc:
        raise RuntimeError(f'CSRF secret is unavailable: {exc}') from exc
    if len(value) < 32:
        raise RuntimeError('CSRF secret must contain at least 32 bytes')
    return value


def csrf_token(access_token: str) -> str:
    return hmac.new(csrf_secret(), access_token.encode(), hashlib.sha256).hexdigest()


def role_for(email: str) -> Role:
    data = load_json(ROLE_FILE, {})
    users = data.get('users', {}) if isinstance(data, dict) else {}
    entry = users.get(email.lower()) if isinstance(users, dict) else None
    role = str(entry.get('role') if isinstance(entry, dict) else entry or '').lower()
    if role not in ROLE_RANK:
        raise HTTPException(status_code=403, detail='identity is not authorized for LGHS Fleet')
    return role  # type: ignore[return-value]


def require_access_config() -> None:
    if not CF_TEAM_DOMAIN.startswith('https://') or not CF_AUDIENCE:
        raise HTTPException(status_code=503, detail='Cloudflare Access validation is not configured')


_jwks: PyJWKClient | None = None
_jwks_domain = ''


def jwks_client() -> PyJWKClient:
    global _jwks, _jwks_domain
    require_access_config()
    if _jwks is None or _jwks_domain != CF_TEAM_DOMAIN:
        _jwks_domain = CF_TEAM_DOMAIN
        _jwks = PyJWKClient(f'{CF_TEAM_DOMAIN}/cdn-cgi/access/certs', cache_keys=True, lifespan=300)
    return _jwks


def verify_access_token(token: str) -> dict[str, Any]:
    try:
        key = jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(token, key.key, algorithms=['RS256'], audience=CF_AUDIENCE, issuer=CF_TEAM_DOMAIN, options={'require': ['exp', 'iat', 'aud', 'iss']})
    except Exception as exc:
        raise HTTPException(status_code=401, detail='invalid Cloudflare Access identity') from exc


async def current_identity(cf_access_jwt_assertion: str | None = Header(default=None, alias='Cf-Access-Jwt-Assertion')) -> Identity:
    if not cf_access_jwt_assertion:
        raise HTTPException(status_code=401, detail='Cloudflare Access identity missing')
    claims = verify_access_token(cf_access_jwt_assertion)
    email = str(claims.get('email') or '').strip().lower(); subject = str(claims.get('sub') or '').strip()
    if not email or not subject:
        raise HTTPException(status_code=401, detail='Cloudflare Access identity is incomplete')
    return Identity(email=email, role=role_for(email), subject=subject, access_token=cf_access_jwt_assertion)


def allow(minimum: Role):
    async def dependency(identity: Identity = Depends(current_identity)) -> Identity:
        if ROLE_RANK[identity.role] < ROLE_RANK[minimum]:
            raise HTTPException(status_code=403, detail='insufficient LGHS Fleet role')
        return identity
    return dependency


async def fleet_request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {'Authorization': f'Bearer {admin_token()}', 'Accept': 'application/json', 'Content-Type': 'application/json'}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=1.5)) as client:
            response = await client.request(method, f'{FLEET_API}{path}', headers=headers, json=body if body is not None else None)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail='Fleet API is temporarily unavailable') from exc
    if response.status_code >= 400:
        try:
            err = response.json()
            detail = str(err.get('error') or err.get('detail') or f'Fleet API returned {response.status_code}') if isinstance(err, dict) else f'Fleet API returned {response.status_code}'
        except ValueError:
            detail = f'Fleet API returned {response.status_code}'
        raise HTTPException(status_code=502 if response.status_code >= 500 else response.status_code, detail=detail)
    try:
        value = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail='Fleet API returned invalid JSON') from exc
    return value if isinstance(value, dict) else {}


async def fleet_get(path: str) -> dict[str, Any]:
    return await fleet_request('GET', path)


async def fleet_post(path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    return await fleet_request('POST', path, body or {})


def _ops_call_sync(payload: dict[str, Any]) -> dict[str, Any]:
    raw = (json.dumps(payload, separators=(',', ':')) + '\n').encode(); client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); client.settimeout(8)
    try:
        client.connect(str(OPS_SOCKET)); client.sendall(raw); data = b''
        while b'\n' not in data and len(data) < 1024 * 1024:
            chunk = client.recv(65536)
            if not chunk: break
            data += chunk
    finally:
        client.close()
    if not data: raise RuntimeError('Fleet operations broker returned no response')
    value = json.loads(data.split(b'\n', 1)[0])
    if not isinstance(value, dict): raise RuntimeError('Fleet operations broker returned invalid data')
    if not value.get('ok'): raise RuntimeError(str(value.get('error') or 'Fleet operation failed'))
    return value


async def ops_call(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_ops_call_sync, payload)
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def connectivity(age: float | None) -> str:
    if age is None or age > 60: return 'offline'
    if age > 15: return 'stale'
    return 'online'


def first_group(groups: Any) -> str:
    if not isinstance(groups, list) or not groups: return 'Ungrouped'
    row = groups[0]
    if isinstance(row, dict): return str(row.get('name') or row.get('group_id') or 'Ungrouped')
    return str(row)


def build_device(row: dict[str, Any], live: dict[str, Any], now: float) -> dict[str, Any]:
    metrics = live.get('metrics', {}) if isinstance(live.get('metrics'), dict) else {}; health = live.get('health', {}) if isinstance(live.get('health'), dict) else {}; inventory = health.get('inventory', {}) if isinstance(health.get('inventory'), dict) else {}; wifi = metrics.get('wifi', {}) if isinstance(metrics.get('wifi'), dict) else {}; network = metrics.get('network', {}) if isinstance(metrics.get('network'), dict) else {}
    received = live.get('received_at') or row.get('last_seen')
    try: age = max(0.0, now - float(received)) if received is not None else None
    except (TypeError, ValueError): age = None
    state = connectivity(age); health_state = str(row.get('health_state') or 'unknown').lower()
    if state == 'offline': health_state = 'unknown'
    tags = row.get('tags') if isinstance(row.get('tags'), list) else []; groups = row.get('groups') if isinstance(row.get('groups'), list) else []; ipv4 = network.get('ipv4') if isinstance(network.get('ipv4'), list) else []; ipv6 = network.get('ipv6') if isinstance(network.get('ipv6'), list) else []
    return {
        'deviceId': str(row.get('device_id') or live.get('device_id') or '?'), 'hostname': str(row.get('hostname') or inventory.get('hostname') or row.get('device_id') or '?'), 'health': health_state if health_state in {'healthy','warning','critical','maintenance','unknown'} else 'unknown', 'connectivity': state,
        'version': str(row.get('current_version') or live.get('version') or row.get('agent_version') or 'unknown'), 'commit': str(row.get('current_commit') or inventory.get('current_commit') or 'unknown'), 'role': str(row.get('role') or inventory.get('role') or 'student'), 'group': first_group(groups), 'tags': [str(x) for x in tags], 'model': str(row.get('model') or inventory.get('model') or 'Raspberry Pi'), 'ramMb': int(row.get('ram_mb') or inventory.get('ram_mb') or 0),
        'cpuPct': metrics.get('cpu_pct'), 'memPct': metrics.get('mem_pct'), 'diskPct': metrics.get('disk_pct'), 'tempC': metrics.get('temp_c'), 'load1': metrics.get('load1'), 'wifiDbm': network.get('signal_dbm', wifi.get('signal_dbm')), 'ssid': network.get('ssid'), 'activeInterface': network.get('active_interface') or wifi.get('interface'), 'ipv4': [str(x) for x in ipv4], 'ipv6': [str(x) for x in ipv6], 'gateway': network.get('gateway'),
        'rxBps': network.get('rx_bps', metrics.get('rx_bps')), 'txBps': network.get('tx_bps', metrics.get('tx_bps')), 'rxBytes': network.get('rx_bytes', metrics.get('rx_bytes')), 'txBytes': network.get('tx_bytes', metrics.get('tx_bytes')), 'rxErrors': network.get('rx_errors'), 'txErrors': network.get('tx_errors'), 'rxDropped': network.get('rx_dropped'), 'txDropped': network.get('tx_dropped'),
        'uptimeSeconds': live.get('uptime_seconds'), 'lastSeenSeconds': age, 'bootId': live.get('boot_id'), 'sequence': live.get('sequence'), 'transport': live.get('transport'), 'updateState': ((live.get('lghs_update') or {}).get('state') if isinstance(live.get('lghs_update'), dict) else None), 'rebootRequired': bool(health.get('reboot_required')), 'throttled': bool(health.get('throttled_now')), 'undervoltage': bool(health.get('undervoltage_now')),
    }


def build_controller_device(controller: dict[str, Any], now: float) -> dict[str, Any]:
    report = controller.get('report', {}) if isinstance(controller.get('report'), dict) else {}; metrics = controller.get('metrics', {}) if isinstance(controller.get('metrics'), dict) else {}; network = metrics.get('network', {}) if isinstance(metrics.get('network'), dict) else {}; services = controller.get('services', {}) if isinstance(controller.get('services'), dict) else {}
    unhealthy = [name for name, state in services.items() if state != 'active']; health = 'healthy' if not unhealthy else 'warning'
    ipv4 = network.get('ipv4') if isinstance(network.get('ipv4'), list) else []; ipv6 = network.get('ipv6') if isinstance(network.get('ipv6'), list) else []
    observed = controller.get('observedAt'); age = max(0.0, now - float(observed)) if isinstance(observed, (int, float)) else 0.0
    return {
        'deviceId': 'LGCSCONT', 'hostname': str(report.get('hostname') or 'LGCSCONT'), 'health': health, 'connectivity': 'online' if age <= 15 else 'stale', 'version': str(report.get('version') or 'unknown'), 'commit': str(report.get('commit') or 'unknown'), 'role': 'controller', 'group': 'Controller', 'tags': ['controller'], 'model': 'Raspberry Pi Controller', 'ramMb': 0,
        'cpuPct': metrics.get('cpu_pct'), 'memPct': metrics.get('mem_pct'), 'diskPct': metrics.get('disk_pct'), 'tempC': metrics.get('temp_c'), 'load1': metrics.get('load1'), 'wifiDbm': network.get('signal_dbm'), 'ssid': network.get('ssid'), 'activeInterface': network.get('active_interface'), 'ipv4': [str(x) for x in ipv4], 'ipv6': [str(x) for x in ipv6], 'gateway': network.get('gateway'), 'rxBps': network.get('rx_bps'), 'txBps': network.get('tx_bps'), 'rxBytes': network.get('rx_bytes'), 'txBytes': network.get('tx_bytes'), 'rxErrors': network.get('rx_errors'), 'txErrors': network.get('tx_errors'), 'rxDropped': network.get('rx_dropped'), 'txDropped': network.get('tx_dropped'), 'uptimeSeconds': metrics.get('uptime_seconds'), 'lastSeenSeconds': age, 'bootId': None, 'sequence': None, 'transport': {'services': services}, 'updateState': None, 'rebootRequired': False, 'throttled': False, 'undervoltage': False,
    }


def build_alerts(live_devices: dict[str, Any], now: float) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for device_id, live in live_devices.items():
        if not isinstance(live, dict): continue
        for warning in live.get('warnings', []) if isinstance(live.get('warnings'), list) else []:
            if not isinstance(warning, dict) or str(warning.get('state') or '').lower() == 'resolved': continue
            seen = warning.get('last_seen') or warning.get('first_seen') or now
            try: age = max(0.0, now - float(seen))
            except (TypeError, ValueError): age = 0.0
            result.append({'id': str(warning.get('warning_id') or f'{device_id}:{warning.get("kind", "warning")}'), 'deviceId': str(warning.get('device_id') or device_id), 'severity': str(warning.get('severity') or 'warning').lower(), 'kind': str(warning.get('kind') or 'health'), 'title': str(warning.get('kind') or 'Fleet warning').replace('-', ' ').replace('_', ' ').title(), 'detail': str(warning.get('detail') or ''), 'observed': None, 'expected': None, 'ageSeconds': age, 'acknowledged': warning.get('acknowledged_at') is not None or str(warning.get('state')) == 'acknowledged'})
    return result


async def build_deployments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = rows[:12]
    async def detail(row: dict[str, Any]) -> dict[str, Any]:
        deployment_id = str(row.get('deployment_id') or '')
        if not deployment_id: return {}
        try: data = await fleet_get(f'/v1/admin/deployments/{deployment_id}')
        except HTTPException: data = {}
        executions = data.get('executions', []) if isinstance(data.get('executions'), list) else []; done = sum(1 for execution in executions if isinstance(execution, dict) and str(execution.get('state')) == 'succeeded'); phases = [int(execution.get('phase') or 0) for execution in executions if isinstance(execution, dict)]
        return {'id': deployment_id, 'name': str(row.get('name') or deployment_id), 'version': str(row.get('target_version') or 'unknown'), 'commit': str(row.get('target_commit') or 'unknown'), 'state': str(row.get('state') or 'queued'), 'completed': done, 'total': len(executions), 'phase': max(phases, default=0) + (1 if executions else 0), 'phases': max(phases, default=-1) + 1, 'createdAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(float(row.get('created_at') or time.time())))}
    return [item for item in await asyncio.gather(*(detail(row) for row in selected)) if item]


app = FastAPI(title='LGHS Fleet Web Gateway', docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS, www_redirect=False)


def middleware_error(status: int, detail: str) -> JSONResponse: return JSONResponse(status_code=status, content={'detail': detail})


@app.middleware('http')
async def security_middleware(request: Request, call_next):
    if request.method not in {'GET','HEAD','OPTIONS'} and request.url.path.startswith('/api/'):
        origin = request.headers.get('origin', '').rstrip('/')
        if origin != PUBLIC_ORIGIN: return middleware_error(403, 'invalid request origin')
        access_token = request.headers.get('cf-access-jwt-assertion', ''); supplied = request.headers.get('x-lghs-csrf', '')
        try: expected = csrf_token(access_token) if access_token else ''
        except RuntimeError: return middleware_error(503, 'CSRF protection is not configured')
        if not access_token or not supplied or not hmac.compare_digest(supplied, expected): return middleware_error(403, 'CSRF validation failed')
    response = await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'; response.headers['Referrer-Policy']='no-referrer'; response.headers['X-Frame-Options']='DENY'; response.headers['Cross-Origin-Opener-Policy']='same-origin'; response.headers['Cross-Origin-Resource-Policy']='same-origin'; response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=(), usb=(), bluetooth=()'; response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'; response.headers['Content-Security-Policy']="default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'"
    if request.url.path.startswith('/api/'): response.headers['Cache-Control']='no-store, max-age=0'; response.headers['Pragma']='no-cache'
    return response


@app.get('/healthz')
async def healthz(): return {'ok': True, 'service': 'lghs-fleet-web-gateway'}


@app.get('/api/v1/session')
async def session(identity: Identity = Depends(allow('viewer'))): return {'authenticated': True, 'email': identity.email, 'role': identity.role, 'csrfToken': csrf_token(identity.access_token)}


_last_overview: dict[str, Any] | None = None; _last_overview_at = 0.0


@app.get('/api/v1/overview')
async def overview(_identity: Identity = Depends(allow('viewer'))):
    global _last_overview, _last_overview_at
    now = time.time()
    try:
        devices_response, deployments_response, live, controller_response = await asyncio.gather(fleet_get('/v1/admin/devices'), fleet_get('/v1/admin/deployments'), ops_call({'op':'live-state'}), ops_call({'op':'controller-status'}))
        admin_devices = devices_response.get('devices', []) if isinstance(devices_response.get('devices'), list) else []; deployments = deployments_response.get('deployments', []) if isinstance(deployments_response.get('deployments'), list) else []; live_devices = live.get('devices', {}) if isinstance(live.get('devices'), dict) else {}; controller = controller_response.get('controller', {}) if isinstance(controller_response.get('controller'), dict) else {}; activity = live.get('activity', []) if isinstance(live.get('activity'), list) else []
        normalized_activity=[]
        for item in activity:
            if not isinstance(item, dict): continue
            normalized_activity.append({**item, 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(float(item.get('at') or now))), 'severity': str(item.get('severity') or 'info') if str(item.get('severity') or 'info') in {'info','warning','critical'} else 'info'})
        device_rows=[build_device(row, live_devices.get(str(row.get('device_id')), {}), now) for row in admin_devices if isinstance(row, dict)]
        device_rows=[row for row in device_rows if row.get('deviceId') != 'LGCSCONT']
        device_rows.insert(0, build_controller_device(controller, now))
        value={'devices':device_rows,'alerts':build_alerts(live_devices,now),'deployments':await build_deployments([row for row in deployments if isinstance(row,dict)]),'activity':normalized_activity,'sudoRequests':live.get('sudo',[]),'settings':live.get('settings',{}),'controller':controller,'generatedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(now)),'degraded':False}
        _last_overview,_last_overview_at=value,now; return value
    except HTTPException:
        if _last_overview is not None and now-_last_overview_at<=120: return {**_last_overview,'degraded':True,'generatedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(now))}
        raise


@app.get('/api/v1/sudo')
async def sudo_list(_identity: Identity = Depends(allow('viewer'))):
    live=await ops_call({'op':'live-state'}); return {'requests':live.get('sudo',[])}


@app.post('/api/v1/sudo/{request_id}/{decision}')
async def sudo_decide(request_id:str,decision:str,identity:Identity=Depends(allow('operator'))):
    if decision not in {'approve','deny'}: raise HTTPException(status_code=400,detail='decision must be approve or deny')
    live=await ops_call({'op':'live-state'}); rows=live.get('sudo',[]) if isinstance(live.get('sudo'),list) else []; match=next((row for row in rows if isinstance(row,dict) and str(row.get('request_id') or row.get('id'))==request_id),None)
    if not match: raise HTTPException(status_code=404,detail='sudo request not found')
    return await ops_call({'op':'sudo-decision','device_id':str(match.get('device_id') or ''),'request_id':request_id,'decision':decision,'actor':identity.email})


@app.post('/api/v1/devices/{device_id}/actions/{action}')
async def device_action(device_id:str,action:str,identity:Identity=Depends(allow('operator'))):
    if device_id.upper()=='LGCSCONT': raise HTTPException(status_code=400,detail='controller actions are managed through controller controls')
    return await ops_call({'op':'device-action','device_id':device_id,'action':action,'actor':identity.email})


@app.post('/api/v1/devices/{device_id}/maintenance')
async def device_maintenance(device_id:str,request:Request,identity:Identity=Depends(allow('operator'))):
    body=await request.json(); policy=body.get('policy') if isinstance(body,dict) else None
    if not isinstance(policy,dict): raise HTTPException(status_code=400,detail='policy must be an object')
    return await fleet_post(f'/v1/admin/maintenance/device/{device_id}',{'policy':policy,'actor':identity.email})


@app.post('/api/v1/devices/{device_id}/maintenance/clear')
async def device_maintenance_clear(device_id:str,identity:Identity=Depends(allow('operator'))): return await fleet_post(f'/v1/admin/maintenance/device/{device_id}/clear',{'actor':identity.email})


@app.post('/api/v1/alerts/{warning_id}/ack')
async def alert_ack(warning_id:str,identity:Identity=Depends(allow('operator'))): return await ops_call({'op':'alert-ack','warning_id':warning_id,'actor':identity.email})


@app.post('/api/v1/groups')
async def group_create(request:Request,identity:Identity=Depends(allow('operator'))):
    body=await request.json(); return await ops_call({'op':'group-create','name':body.get('name'),'description':body.get('description'),'actor':identity.email})


@app.post('/api/v1/groups/{group_id}/members/{device_id}')
async def group_add(group_id:str,device_id:str,identity:Identity=Depends(allow('operator'))): return await ops_call({'op':'group-member','group_id':group_id,'device_id':device_id,'add':True,'actor':identity.email})


@app.delete('/api/v1/groups/{group_id}/members/{device_id}')
async def group_remove(group_id:str,device_id:str,identity:Identity=Depends(allow('operator'))): return await ops_call({'op':'group-member','group_id':group_id,'device_id':device_id,'add':False,'actor':identity.email})


@app.post('/api/v1/deployments')
async def deployment_create(request:Request,identity:Identity=Depends(allow('operator'))):
    body=await request.json()
    if not isinstance(body,dict): raise HTTPException(status_code=400,detail='invalid deployment body')
    body=dict(body); body['created_by']=identity.email
    return await fleet_post('/v1/admin/deployments',body)


@app.post('/api/v1/deployments/{deployment_id}/{action}')
async def deployment_action(deployment_id:str,action:str,request:Request,identity:Identity=Depends(allow('operator'))):
    allowed={'retry-failed','resume','continue','cancel-remaining','rollback','advance','dispatch'}
    if action not in allowed: raise HTTPException(status_code=400,detail='unsupported deployment action')
    try: body=await request.json()
    except Exception: body={}
    if not isinstance(body,dict): body={}
    body=dict(body); body['actor']=identity.email
    return await fleet_post(f'/v1/admin/deployments/{deployment_id}/{action}',body)


@app.put('/api/v1/settings/{key:path}')
async def setting_set(key:str,request:Request,identity:Identity=Depends(allow('owner'))):
    body=await request.json(); return await ops_call({'op':'settings-set','key':key,'value':body.get('value'),'actor':identity.email})


app.frontend('/',directory=str(DIST),fallback='index.html',check_dir=False)
