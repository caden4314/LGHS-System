'''Automatic rollout reconciliation and soak timing for LGHS 0.6.'''
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from .maintenance import phase_maintenance_gate
from .rollout import advance_rollout, dispatch_phase, rollout_status

RUNTIME_PREFIX = 'rollout-runtime:'


def _decode(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or '{}'))
    except Exception:
        parsed = {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _policy(deployment: dict[str, Any]) -> dict[str, Any]:
    return _decode(deployment.get('policy_json'))


def _strategy(deployment: dict[str, Any]) -> dict[str, Any]:
    return _decode(deployment.get('strategy_json'))


def _audit(store: Any, deployment_id: str, phase: int, action: str, detail: dict[str, Any], *, severity: str = 'info', now: float) -> None:
    payload = {'deployment_id': deployment_id, 'phase': int(phase), 'action': action, **dict(detail)}
    with store.transaction() as db:
        db.execute(
            'INSERT INTO audit_events(device_id,kind,severity,created_at,sequence,detail_json) VALUES(NULL,?,?,?,?,?)',
            ('deployment-gate', severity, now, None, json.dumps(payload, sort_keys=True, separators=(',', ':'))),
        )


def load_runtime(store: Any, deployment_id: str) -> dict[str, Any]:
    key = RUNTIME_PREFIX + deployment_id
    with store.connect() as db:
        row = db.execute('SELECT value_json FROM settings WHERE key=?', (key,)).fetchone()
    return _decode(row['value_json']) if row else {}


def save_runtime(store: Any, deployment_id: str, runtime: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    key = RUNTIME_PREFIX + deployment_id
    value = json.dumps(runtime, sort_keys=True, separators=(',', ':'))
    with store.transaction() as db:
        db.execute(
            '''INSERT INTO settings(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
            (key, value, ts),
        )
    return runtime


def _reset_soak(runtime: dict[str, Any], active_phase: int | None) -> dict[str, Any]:
    runtime = dict(runtime)
    runtime['active_phase'] = active_phase
    runtime['ready_since'] = None
    runtime['next_action_at'] = None
    runtime['maintenance_next_open_at'] = None
    runtime['maintenance_blocked_devices'] = []
    return runtime


def _gate_snapshot(gate: dict[str, Any]) -> dict[str, Any]:
    details = gate.get('health_details', {}) if isinstance(gate.get('health_details'), dict) else {}
    compact_details: dict[str, Any] = {}
    for device, value in sorted(details.items()):
        item = value if isinstance(value, dict) else {}
        compact_details[device] = {
            'allowed': bool(item.get('allowed')),
            'mode': item.get('mode'),
            'reason': item.get('reason'),
            'blocked_checks': [
                {
                    'id': check.get('id'),
                    'state': check.get('state'),
                    'severity': check.get('severity'),
                    'observed': check.get('observed'),
                    'expected': check.get('expected'),
                    'remediation': check.get('remediation'),
                }
                for check in item.get('blocked_checks', []) if isinstance(check, dict)
            ],
        }
    return {
        'state': gate.get('state'),
        'reason': gate.get('reason'),
        'failed': list(gate.get('failed') or []),
        'pending': list(gate.get('pending') or []),
        'health_blocked': list(gate.get('health_blocked') or []),
        'verified': list(gate.get('verified') or []),
        'health_details': compact_details,
    }


def _record_gate_transition(store: Any, deployment_id: str, phase: int, gate: dict[str, Any], runtime: dict[str, Any], *, now: float) -> dict[str, Any]:
    snapshot = _gate_snapshot(gate)
    encoded = json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()
    signature = hashlib.sha256(encoded).hexdigest()
    key = f'gate_signature_phase_{int(phase)}'
    if runtime.get(key) == signature:
        return runtime
    runtime[key] = signature
    runtime['last_gate_phase'] = int(phase)
    runtime['last_gate_state'] = gate.get('state')
    runtime['last_gate_reason'] = gate.get('reason')
    runtime['last_gate_at'] = now
    severity = 'warning' if gate.get('state') in {'paused', 'waiting'} and (gate.get('failed') or gate.get('health_blocked')) else 'info'
    _audit(store, deployment_id, phase, 'gate-transition', snapshot, severity=severity, now=now)
    save_runtime(store, deployment_id, runtime, now=now)
    return runtime


def _maintenance_wait(store: Any, deployment_id: str, phase: int, runtime: dict[str, Any], *, now: float) -> dict[str, Any] | None:
    gate = phase_maintenance_gate(store, deployment_id, phase, now=now)
    if gate['allowed']:
        if runtime.get('maintenance_next_open_at') is not None or runtime.get('maintenance_blocked_devices'):
            previous = list(runtime.get('maintenance_blocked_devices') or [])
            runtime['maintenance_next_open_at'] = None
            runtime['maintenance_blocked_devices'] = []
            save_runtime(store, deployment_id, runtime, now=now)
            _audit(store, deployment_id, phase, 'maintenance-open', {'previously_blocked_devices': previous}, now=now)
        return None
    previous = list(runtime.get('maintenance_blocked_devices') or [])
    current = list(gate.get('blocked_devices') or [])
    runtime['maintenance_next_open_at'] = gate.get('next_open_at')
    runtime['maintenance_blocked_devices'] = current
    save_runtime(store, deployment_id, runtime, now=now)
    if previous != current:
        _audit(store, deployment_id, phase, 'maintenance-wait', {'blocked_devices': current, 'next_open_at': gate.get('next_open_at')}, severity='warning', now=now)
    return {
        'deployment_id': deployment_id,
        'action': 'maintenance-wait',
        'phase': int(phase),
        'blocked_devices': gate['blocked_devices'],
        'next_open_at': gate.get('next_open_at'),
        'gate': gate,
        'runtime': runtime,
    }


def reconcile_deployment(store: Any, deployment_id: str, *, now: float | None = None) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    deployment = store.get_deployment(deployment_id)
    if not deployment:
        raise KeyError(deployment_id)
    state = str(deployment.get('state') or 'queued').lower()
    policy = _policy(deployment)
    strategy = _strategy(deployment)
    runtime = load_runtime(store, deployment_id)
    if state in {'canceled', 'failed', 'succeeded'}:
        return {'deployment_id': deployment_id, 'action': 'terminal', 'state': state, 'runtime': runtime}
    if state == 'paused':
        return {'deployment_id': deployment_id, 'action': 'paused', 'state': state, 'runtime': runtime, 'reason': deployment.get('paused_reason') or ''}
    if not bool(policy.get('auto_advance')):
        return {'deployment_id': deployment_id, 'action': 'manual', 'state': state, 'runtime': runtime}

    status = rollout_status(store, deployment_id, now=ts)
    active = status['active_phase']
    if active is None:
        phase = status['next_phase']
        if phase is None:
            return {'deployment_id': deployment_id, 'action': 'empty', 'state': state, 'runtime': runtime}
        if bool(policy.get('respect_maintenance')):
            waiting = _maintenance_wait(store, deployment_id, phase, runtime, now=ts)
            if waiting is not None:
                return waiting
        command_ids = dispatch_phase(store, deployment_id, phase, now=ts)
        runtime = _reset_soak(runtime, phase)
        runtime['phase_started_at'] = ts
        save_runtime(store, deployment_id, runtime, now=ts)
        return {'deployment_id': deployment_id, 'action': 'dispatched', 'phase': phase, 'command_ids': command_ids, 'runtime': runtime}

    gate = next(item for item in status['phases'] if item['phase'] == active)
    runtime = _record_gate_transition(store, deployment_id, active, gate, runtime, now=ts)
    if gate['state'] == 'paused':
        with store.transaction() as db:
            db.execute(
                "UPDATE deployments SET state='paused',paused_reason=?,updated_at=? WHERE deployment_id=?",
                (gate['reason'], ts, deployment_id),
            )
        runtime = _reset_soak(runtime, active)
        runtime['paused_at'] = ts
        runtime['paused_reason'] = gate['reason']
        save_runtime(store, deployment_id, runtime, now=ts)
        _audit(store, deployment_id, active, 'paused', {'reason': gate['reason']}, severity='warning', now=ts)
        return {'deployment_id': deployment_id, 'action': 'paused', 'phase': active, 'reason': gate['reason'], 'gate': gate, 'runtime': runtime}

    if gate['state'] != 'ready':
        if runtime.get('ready_since') is not None or runtime.get('active_phase') != active:
            runtime = _reset_soak(runtime, active)
            runtime['phase_started_at'] = runtime.get('phase_started_at') or ts
            save_runtime(store, deployment_id, runtime, now=ts)
        return {'deployment_id': deployment_id, 'action': 'waiting', 'phase': active, 'gate': gate, 'runtime': runtime}

    soak_seconds = max(0, int(strategy.get('soak_seconds') or 0))
    if runtime.get('active_phase') != active:
        runtime = _reset_soak(runtime, active)
    ready_since = runtime.get('ready_since')
    if ready_since is None:
        ready_since = ts
        runtime['ready_since'] = ts
        runtime['next_action_at'] = ts + soak_seconds
        save_runtime(store, deployment_id, runtime, now=ts)
        _audit(store, deployment_id, active, 'soak-started', {'soak_seconds': soak_seconds, 'next_action_at': runtime['next_action_at']}, now=ts)
    next_action = float(runtime.get('next_action_at') or ready_since)
    if ts < next_action:
        return {
            'deployment_id': deployment_id,
            'action': 'soaking',
            'phase': active,
            'remaining_seconds': max(0.0, round(next_action - ts, 3)),
            'gate': gate,
            'runtime': runtime,
        }

    before = rollout_status(store, deployment_id, now=ts)
    next_phase = before['next_phase']
    if next_phase is not None and bool(policy.get('respect_maintenance')):
        waiting = _maintenance_wait(store, deployment_id, next_phase, runtime, now=ts)
        if waiting is not None:
            waiting['completed_phase'] = active
            return waiting
    after = advance_rollout(store, deployment_id, now=ts)
    if next_phase is None:
        runtime['completed_at'] = ts
        runtime['next_action_at'] = None
        runtime['maintenance_next_open_at'] = None
        runtime['maintenance_blocked_devices'] = []
        save_runtime(store, deployment_id, runtime, now=ts)
        return {'deployment_id': deployment_id, 'action': 'completed', 'phase': active, 'status': after, 'runtime': runtime}
    runtime = _reset_soak(runtime, next_phase)
    runtime['phase_started_at'] = ts
    save_runtime(store, deployment_id, runtime, now=ts)
    command_ids = [
        row['command_id'] for row in store.list_deployment_executions(deployment_id)
        if int(row.get('phase') or 0) == int(next_phase) and row.get('command_id')
    ]
    return {'deployment_id': deployment_id, 'action': 'advanced', 'phase': next_phase, 'command_ids': command_ids, 'status': after, 'runtime': runtime}


def reconcile_all(store: Any, *, now: float | None = None) -> list[dict[str, Any]]:
    ts = time.time() if now is None else float(now)
    with store.connect() as db:
        rows = db.execute("SELECT deployment_id FROM deployments WHERE state IN ('queued','running','paused') ORDER BY created_at").fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        deployment_id = str(row['deployment_id'])
        try:
            results.append(reconcile_deployment(store, deployment_id, now=ts))
        except Exception as exc:
            results.append({'deployment_id': deployment_id, 'action': 'error', 'error': str(exc)})
    return results
