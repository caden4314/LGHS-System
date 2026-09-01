from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
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
TOKEN_FILE = Path(os.environ.get('LGHS_WEB_FLEET_TOKEN_FILE', '/etc/lghs/fleet-api-tokens.json'))
CACHE_FILE = Path(os.environ.get('LGHS_WEB_FLEET_CACHE', '/var/lib/lghs/fleet-cache.json'))
ROLE_FILE = Path(os.environ.get('LGHS_WEB_ROLE_FILE', '/etc/lghs/web-roles.json'))
CSRF_FILE = Path(os.environ.get('LGHS_WEB_CSRF_FILE', '/etc/lghs/web-csrf.key'))
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
        claims = jwt.decode(
            token,
            key.key,
            algorithms=['RS256'],
            audience=CF_AUDIENCE,
            issuer=CF_TEAM_DOMAIN,
            options={'require': ['exp', 'iat', 'aud', 'iss']},
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail='invalid Cloudflare Access identity') from exc
    return claims


async def current_identity(
    cf_access_jwt_assertion: str | None = Header(default=None, alias='Cf-Access-Jwt-Assertion'),
) -> Identity:
    if not cf_access_jwt_assertion:
        raise HTTPException(status_code=401, detail='Cloudflare Access identity missing')
    claims = verify_access_token(cf_access_jwt_assertion)
    email = str(claims.get('email') or '').strip().lower()
    subject = str(claims.get('sub') or '').strip()
    if not email or not subject:
        raise HTTPException(status_code=401, detail='Cloudflare Access identity is incomplete')
    return Identity(email=email, role=role_for(email), subject=subject, access_token=cf_access_jwt_assertion)


def allow(minimum: Role):
    async def dependency(identity: Identity = Depends(current_identity)) -> Identity:
        if ROLE_RANK[identity.role] < ROLE_RANK[minimum]:
            raise HTTPException(status_code=403, detail='insufficient LGHS Fleet role')
        return identity
    return dependency


async def fleet_get(path: str) -> dict[str, Any]:
    headers = {'Authorization': f'Bearer {admin_token()}', 'Accept': 'application/json'}
    async with httpx.AsyncClient(timeout=8.0) as client:
        response = await client.get(f'{FLEET_API}{path}', headers=headers)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f'Fleet API returned {response.status_code}')
    try:
        value = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail='Fleet API returned invalid JSON') from exc
    return value if isinstance(value, dict) else {}


def connectivity(age: float | None) -> str:
    if age is None or age > 60:
        return 'offline'
    if age > 15:
        return 'stale'
    return 'online'


def first_group(groups: Any) -> str:
    if not isinstance(groups, list) or not groups:
        return 'Ungrouped'
    row = groups[0]
    if isinstance(row, dict):
        return str(row.get('name') or row.get('group_id') or 'Ungrouped')
    return str(row)


def build_device(row: dict[str, Any], cached: dict[str, Any], now: float) -> dict[str, Any]:
    metrics = cached.get('metrics', {}) if isinstance(cached.get('metrics'), dict) else {}
    health = cached.get('health', {}) if isinstance(cached.get('health'), dict) else {}
    inventory = health.get('inventory', {}) if isinstance(health.get('inventory'), dict) else {}
    wifi = metrics.get('wifi', {}) if isinstance(metrics.get('wifi'), dict) else {}
    received = cached.get('received_at')
    try:
        age = max(0.0, now - float(received)) if received is not None else None
    except (TypeError, ValueError):
        age = None
    state = connectivity(age)
    health_state = str(row.get('health_state') or 'unknown').lower()
    if state == 'offline':
        health_state = 'unknown'
    tags = row.get('tags') if isinstance(row.get('tags'), list) else []
    groups = row.get('groups') if isinstance(row.get('groups'), list) else []
    return {
        'deviceId': str(row.get('device_id') or cached.get('device_id') or '?'),
        'hostname': str(row.get('hostname') or inventory.get('hostname') or row.get('device_id') or '?'),
        'health': health_state if health_state in {'healthy', 'warning', 'critical', 'maintenance', 'unknown'} else 'unknown',
        'connectivity': state,
        'version': str(row.get('current_version') or cached.get('version') or row.get('agent_version') or 'unknown'),
        'commit': str(row.get('current_commit') or inventory.get('current_commit') or 'unknown'),
        'role': str(row.get('role') or inventory.get('role') or 'student'),
        'group': first_group(groups),
        'tags': [str(x) for x in tags],
        'model': str(row.get('model') or inventory.get('model') or 'Raspberry Pi'),
        'ramMb': int(row.get('ram_mb') or inventory.get('ram_mb') or 0),
        'cpuPct': metrics.get('cpu_pct'),
        'memPct': metrics.get('mem_pct'),
        'diskPct': metrics.get('disk_pct'),
        'tempC': metrics.get('temp_c'),
        'wifiDbm': wifi.get('signal_dbm'),
        'rxBps': metrics.get('rx_bps'),
        'txBps': metrics.get('tx_bps'),
        'uptimeSeconds': cached.get('uptime_seconds'),
        'lastSeenSeconds': age,
        'updateState': ((cached.get('lghs_update') or {}).get('state') if isinstance(cached.get('lghs_update'), dict) else None),
        'rebootRequired': bool(health.get('reboot_required')),
        'throttled': bool(health.get('throttled_now')),
        'undervoltage': bool(health.get('undervoltage_now')),
    }


def build_alerts(cache_devices: dict[str, Any], now: float) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for device_id, cached in cache_devices.items():
        if not isinstance(cached, dict):
            continue
        for warning in cached.get('warnings', []) if isinstance(cached.get('warnings'), list) else []:
            if not isinstance(warning, dict):
                continue
            if str(warning.get('state') or 'open').lower() in {'resolved', 'closed'}:
                continue
            seen = warning.get('last_seen') or warning.get('first_seen') or now
            try:
                age = max(0.0, now - float(seen))
            except (TypeError, ValueError):
                age = 0.0
            result.append({
                'id': str(warning.get('warning_id') or warning.get('id') or f'{device_id}:{warning.get("kind", "warning")}'),
                'deviceId': str(warning.get('device_id') or device_id),
                'severity': str(warning.get('severity') or 'warning').lower(),
                'kind': str(warning.get('kind') or 'health'),
                'title': str(warning.get('kind') or 'Fleet warning').replace('-', ' ').replace('_', ' ').title(),
                'detail': str(warning.get('detail') or ''),
                'observed': None,
                'expected': None,
                'ageSeconds': age,
                'acknowledged': warning.get('acknowledged_at') is not None,
            })
    return result


async def build_deployments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = rows[:8]

    async def detail(row: dict[str, Any]) -> dict[str, Any]:
        deployment_id = str(row.get('deployment_id') or '')
        if not deployment_id:
            return {}
        try:
            data = await fleet_get(f'/v1/admin/deployments/{deployment_id}')
        except HTTPException:
            data = {}
        executions = data.get('executions', []) if isinstance(data.get('executions'), list) else []
        done = sum(1 for execution in executions if isinstance(execution, dict) and str(execution.get('state')) == 'succeeded')
        phases = [int(execution.get('phase') or 0) for execution in executions if isinstance(execution, dict)]
        return {
            'id': deployment_id,
            'name': str(row.get('name') or deployment_id),
            'version': str(row.get('target_version') or 'unknown'),
            'commit': str(row.get('target_commit') or 'unknown'),
            'state': str(row.get('state') or 'queued'),
            'completed': done,
            'total': len(executions),
            'phase': max(phases, default=0) + (1 if executions else 0),
            'phases': max(phases, default=-1) + 1,
            'createdAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(float(row.get('created_at') or time.time()))),
        }

    return [item for item in await asyncio.gather(*(detail(row) for row in selected)) if item]


app = FastAPI(
    title='LGHS Fleet Web Gateway',
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS, www_redirect=False)


def middleware_error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={'detail': detail})


@app.middleware('http')
async def security_middleware(request: Request, call_next):
    if request.method not in {'GET', 'HEAD', 'OPTIONS'} and request.url.path.startswith('/api/'):
        origin = request.headers.get('origin', '').rstrip('/')
        if origin != PUBLIC_ORIGIN:
            return middleware_error(403, 'invalid request origin')
        access_token = request.headers.get('cf-access-jwt-assertion', '')
        supplied = request.headers.get('x-lghs-csrf', '')
        try:
            expected = csrf_token(access_token) if access_token else ''
        except RuntimeError:
            return middleware_error(503, 'CSRF protection is not configured')
        if not access_token or not supplied or not hmac.compare_digest(supplied, expected):
            return middleware_error(403, 'CSRF validation failed')

    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=(), usb=(), bluetooth=()'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
        "form-action 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'"
    )
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        response.headers['Pragma'] = 'no-cache'
    return response


@app.get('/healthz')
async def healthz():
    return {'ok': True, 'service': 'lghs-fleet-web-gateway'}


@app.get('/api/v1/session')
async def session(identity: Identity = Depends(allow('viewer'))):
    return {
        'authenticated': True,
        'email': identity.email,
        'role': identity.role,
        'csrfToken': csrf_token(identity.access_token),
    }


@app.get('/api/v1/overview')
async def overview(_identity: Identity = Depends(allow('viewer'))):
    now = time.time()
    devices_response, deployments_response = await asyncio.gather(
        fleet_get('/v1/admin/devices'),
        fleet_get('/v1/admin/deployments'),
    )
    admin_devices = devices_response.get('devices', []) if isinstance(devices_response.get('devices'), list) else []
    deployments = deployments_response.get('deployments', []) if isinstance(deployments_response.get('deployments'), list) else []
    cache = load_json(CACHE_FILE, {})
    cache_devices = cache.get('devices', {}) if isinstance(cache, dict) and isinstance(cache.get('devices'), dict) else {}
    device_rows = [build_device(row, cache_devices.get(str(row.get('device_id')), {}), now) for row in admin_devices if isinstance(row, dict)]
    return {
        'devices': device_rows,
        'alerts': build_alerts(cache_devices, now),
        'deployments': await build_deployments([row for row in deployments if isinstance(row, dict)]),
        'activity': [],
        'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now)),
    }


# FastAPI's frontend helper serves an already-built Vite application and falls
# back to index.html for client-side routes. API routes above take precedence.
app.frontend('/', directory=str(DIST), fallback='index.html', check_dir=False)
