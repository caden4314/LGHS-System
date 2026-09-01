'''Reason-aware post-update health gates for LGHS 0.6.'''
from __future__ import annotations

import time
from typing import Any, Mapping

from .protocol import normalize_device_id

DEFAULT_REQUIRED_CHECKS = (
    'service.NetworkManager',
    'service.lghs-policy',
    'service.lghs-agent',
    'service.lghs-command-executor',
    'storage.root',
    'storage.root-writable',
    'clock.synchronized',
    'power.undervoltage',
    'hardware.throttling',
    'system.reboot-required',
    'transport.controller',
)
DEFAULT_MAX_REPORT_AGE_SECONDS = 45


def normalize_health_gate(raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    value = dict(raw or {})
    supplied = value.get('required_checks', DEFAULT_REQUIRED_CHECKS)
    if not isinstance(supplied, (list, tuple, set)) or not supplied:
        raise ValueError('health_gate.required_checks must be a non-empty list')
    required: list[str] = []
    for item in supplied:
        check_id = str(item or '').strip()
        if not check_id or len(check_id) > 128:
            raise ValueError('invalid health gate check id')
        if check_id not in required:
            required.append(check_id)
    try:
        max_age = int(value.get('max_report_age_seconds', DEFAULT_MAX_REPORT_AGE_SECONDS))
    except Exception as exc:
        raise ValueError('invalid health gate max_report_age_seconds') from exc
    if max_age < 10 or max_age > 600:
        raise ValueError('health gate max_report_age_seconds must be between 10 and 600')
    return {
        'required_checks': required,
        'max_report_age_seconds': max_age,
        'block_any_critical_failure': bool(value.get('block_any_critical_failure', True)),
    }


def _legacy_gate(inventory: Mapping[str, Any], require_health: str) -> dict[str, Any]:
    health = str(inventory.get('health_state') or 'unknown').lower()
    allowed_states = {'healthy'} if require_health == 'healthy' else {'healthy', 'warning'}
    allowed = health in allowed_states
    return {
        'allowed': allowed,
        'mode': 'legacy',
        'health_state': health,
        'report_age_seconds': None,
        'required_checks': [],
        'blocked_checks': [] if allowed else [{
            'id': 'legacy.health-state',
            'state': health,
            'severity': 'critical' if health in {'critical', 'offline'} else 'warning',
            'observed': health,
            'expected': sorted(allowed_states),
            'remediation': 'inspect:device-health',
            'reason': f'legacy health state is {health}',
        }],
        'advisories': [],
        'reason': 'legacy aggregate health accepted' if allowed else f'legacy aggregate health blocked: {health}',
    }


def device_health_gate(
    store: Any,
    device_id: str,
    *,
    strategy: Mapping[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    device = normalize_device_id(device_id)
    strategy_obj = dict(strategy or {})
    require_health = str(strategy_obj.get('require_health') or 'healthy').lower()
    inventory = store.get_device(device) or {}
    latest = store.latest_telemetry(device)
    if not latest:
        return _legacy_gate(inventory, require_health)

    payload = latest.get('payload', {}) if isinstance(latest, Mapping) else {}
    report = payload.get('health_report', {}) if isinstance(payload, Mapping) else {}
    try:
        version = int(report.get('health_version') or 0) if isinstance(report, Mapping) else 0
    except Exception:
        version = 0
    checks_raw = report.get('checks', []) if isinstance(report, Mapping) else []
    if version < 2 or not isinstance(checks_raw, list):
        return _legacy_gate(inventory, require_health)

    config = normalize_health_gate(strategy_obj.get('health_gate'))
    received_at = float(latest.get('received_at') or 0)
    age = max(0.0, ts - received_at) if received_at else float('inf')
    check_map: dict[str, dict[str, Any]] = {}
    for raw in checks_raw:
        if not isinstance(raw, Mapping):
            continue
        check_id = str(raw.get('id') or '').strip()
        if not check_id:
            continue
        check_map[check_id] = dict(raw)

    blocked: list[dict[str, Any]] = []
    advisories: list[dict[str, Any]] = []
    if age > int(config['max_report_age_seconds']):
        blocked.append({
            'id': 'telemetry.freshness',
            'state': 'fail',
            'severity': 'critical',
            'observed': round(age, 3),
            'expected': f"<={config['max_report_age_seconds']} seconds",
            'remediation': 'inspect:agent-controller-connectivity',
            'reason': f'telemetry is {round(age, 1)} seconds old',
        })

    required = list(config['required_checks'])
    for check_id in required:
        check = check_map.get(check_id)
        if check is None:
            blocked.append({
                'id': check_id,
                'state': 'missing',
                'severity': 'critical',
                'observed': None,
                'expected': 'pass',
                'remediation': 'update:agent-health-schema',
                'reason': 'required health check missing from device report',
            })
            continue
        state = str(check.get('state') or 'unknown').lower()
        if state != 'pass':
            item = dict(check)
            item['reason'] = f"required check {check_id} is {state}"
            blocked.append(item)

    for check_id, check in sorted(check_map.items()):
        state = str(check.get('state') or 'unknown').lower()
        severity = str(check.get('severity') or 'warning').lower()
        if check_id in required:
            continue
        if state != 'pass':
            item = dict(check)
            item['reason'] = f"advisory check {check_id} is {state}"
            if config['block_any_critical_failure'] and severity == 'critical':
                blocked.append(item)
            else:
                advisories.append(item)

    allowed = not blocked
    reason = 'all required post-update health checks passed'
    if blocked:
        reason = '; '.join(str(item.get('reason') or item.get('id') or 'health check blocked') for item in blocked[:3])
        if len(blocked) > 3:
            reason += f'; +{len(blocked) - 3} more'
    return {
        'device_id': device,
        'allowed': allowed,
        'mode': 'structured-v2',
        'health_state': str(inventory.get('health_state') or 'unknown').lower(),
        'report_age_seconds': round(age, 3) if age != float('inf') else None,
        'received_at': received_at or None,
        'health_version': version,
        'required_checks': required,
        'blocked_checks': blocked,
        'advisories': advisories,
        'reason': reason,
    }
