'''Frozen-target and phased rollout planning for LGHS 0.6.'''
from __future__ import annotations

import json
import math
import time
from typing import Any, Mapping

from .protocol import TERMINAL_COMMAND_STATES, normalize_device_id

FAILURE_STATES = frozenset(TERMINAL_COMMAND_STATES - {'succeeded'})
OPEN_STATES = frozenset({'queued', 'delivered', 'received', 'accepted', 'running'})


class TargetError(ValueError):
    pass


class StrategyError(ValueError):
    pass


def _normalize_selector(selector: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(selector, Mapping):
        raise TargetError('target selector must be an object')
    supplied = [key for key in ('device_id', 'device_ids', 'group_id', 'tag', 'all') if selector.get(key) not in (None, False, '', [])]
    if len(supplied) != 1:
        raise TargetError('target selector must specify exactly one of device_id, device_ids, group_id, tag, or all')
    key = supplied[0]
    if key == 'device_id':
        return {'device_id': normalize_device_id(selector[key])}
    if key == 'device_ids':
        raw = selector[key]
        if not isinstance(raw, (list, tuple, set)) or not raw:
            raise TargetError('device_ids must be a non-empty list')
        return {'device_ids': sorted({normalize_device_id(item) for item in raw})}
    if key == 'group_id':
        value = str(selector[key]).strip().lower()
        if not value:
            raise TargetError('group_id is required')
        return {'group_id': value}
    if key == 'tag':
        value = str(selector[key]).strip().lower()
        if not value or len(value) > 128 or any(ch.isspace() for ch in value):
            raise TargetError('invalid tag')
        return {'tag': value}
    return {'all': True}


def resolve_targets(store: Any, selector: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    normalized = _normalize_selector(selector)
    with store.connect() as db:
        if 'device_id' in normalized:
            rows = db.execute('SELECT device_id FROM devices WHERE device_id=?', (normalized['device_id'],)).fetchall()
        elif 'device_ids' in normalized:
            wanted = normalized['device_ids']
            marks = ','.join('?' for _ in wanted)
            rows = db.execute(f'SELECT device_id FROM devices WHERE device_id IN ({marks}) ORDER BY device_id', tuple(wanted)).fetchall()
            found = {str(row['device_id']) for row in rows}
            missing = [device for device in wanted if device not in found]
            if missing:
                raise TargetError('unknown device(s): ' + ','.join(missing))
        elif 'group_id' in normalized:
            rows = db.execute('''SELECT m.device_id FROM group_members m JOIN devices d ON d.device_id=m.device_id WHERE m.group_id=? ORDER BY m.device_id''', (normalized['group_id'],)).fetchall()
        elif 'tag' in normalized:
            rows = db.execute('''SELECT t.device_id FROM device_tags t JOIN devices d ON d.device_id=t.device_id WHERE t.tag=? ORDER BY t.device_id''', (normalized['tag'],)).fetchall()
        else:
            rows = db.execute('SELECT device_id FROM devices ORDER BY device_id').fetchall()
    devices = sorted({str(row['device_id']) for row in rows})
    if not devices:
        raise TargetError('target selector matched no enrolled devices')
    return normalized, devices


def normalize_strategy(strategy: Mapping[str, Any] | None, device_count: int) -> dict[str, Any]:
    raw = dict(strategy or {})
    kind = str(raw.get('type') or 'all-at-once').strip().lower()
    if kind in {'all', 'all_at_once'}:
        kind = 'all-at-once'
    if kind not in {'all-at-once', 'phased'}:
        raise StrategyError('strategy type must be all-at-once or phased')
    if device_count < 1:
        raise StrategyError('deployment has no devices')
    if kind == 'all-at-once':
        return {
            'type': 'all-at-once',
            'canary_count': 0,
            'wave_percentages': [100],
            'canary_tag': None,
            'soak_seconds': 0,
            'failure_threshold_count': max(2, int(raw.get('failure_threshold_count') or 2)),
            'failure_threshold_percent': float(raw.get('failure_threshold_percent') or 10.0),
            'require_health': str(raw.get('require_health') or 'healthy').lower(),
        }
    try:
        canary_count = int(raw.get('canary_count') or 1)
    except Exception as exc:
        raise StrategyError('invalid canary_count') from exc
    if not 1 <= canary_count <= device_count:
        raise StrategyError('canary_count must be between 1 and the target device count')
    waves = raw.get('wave_percentages', [20, 50, 100])
    if not isinstance(waves, (list, tuple)) or not waves:
        raise StrategyError('wave_percentages must be a non-empty list')
    normalized_waves: list[int] = []
    previous = 0
    for item in waves:
        try:
            value = int(item)
        except Exception as exc:
            raise StrategyError('wave percentages must be integers') from exc
        if value <= previous or value < 1 or value > 100:
            raise StrategyError('wave percentages must be strictly increasing values from 1 to 100')
        normalized_waves.append(value)
        previous = value
    if normalized_waves[-1] != 100:
        normalized_waves.append(100)
    soak = max(0, int(raw.get('soak_seconds') or 300))
    count_threshold = max(1, int(raw.get('failure_threshold_count') or 2))
    percent_threshold = float(raw.get('failure_threshold_percent') or 10.0)
    if percent_threshold <= 0 or percent_threshold > 100:
        raise StrategyError('failure_threshold_percent must be >0 and <=100')
    canary_tag = str(raw.get('canary_tag') or '').strip().lower() or None
    return {
        'type': 'phased',
        'canary_count': canary_count,
        'wave_percentages': normalized_waves,
        'canary_tag': canary_tag,
        'soak_seconds': soak,
        'failure_threshold_count': count_threshold,
        'failure_threshold_percent': percent_threshold,
        'require_health': str(raw.get('require_health') or 'healthy').lower(),
    }


def plan_phases(store: Any, devices: list[str], strategy: Mapping[str, Any] | None) -> tuple[dict[str, Any], dict[int, list[str]]]:
    frozen = sorted({normalize_device_id(device) for device in devices})
    normalized = normalize_strategy(strategy, len(frozen))
    if normalized['type'] == 'all-at-once':
        return normalized, {0: frozen}
    ordered = list(frozen)
    canary_tag = normalized.get('canary_tag')
    if canary_tag:
        with store.connect() as db:
            tagged = {str(row['device_id']) for row in db.execute('SELECT device_id FROM device_tags WHERE tag=?', (canary_tag,)).fetchall()}
        ordered = [device for device in frozen if device in tagged] + [device for device in frozen if device not in tagged]
    canary_count = int(normalized['canary_count'])
    phases: dict[int, list[str]] = {0: ordered[:canary_count]}
    assigned = canary_count
    phase = 1
    total = len(ordered)
    for percentage in normalized['wave_percentages']:
        target_total = max(canary_count, int(math.ceil(total * int(percentage) / 100.0)))
        if target_total <= assigned:
            continue
        phases[phase] = ordered[assigned:target_total]
        assigned = target_total
        phase += 1
    if assigned < total:
        phases[phase] = ordered[assigned:]
    return normalized, phases


def freeze_deployment(
    store: Any,
    *,
    name: str,
    target_commit: str,
    selector: Mapping[str, Any],
    target_version: str | None = None,
    created_by: str | None = None,
    strategy: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    deployment_id: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    normalized_selector, devices = resolve_targets(store, selector)
    normalized_strategy, phases = plan_phases(store, devices, strategy)
    frozen_target = {
        'selector': normalized_selector,
        'resolved_devices': devices,
        'resolved_at': ts,
    }
    did = store.create_deployment(
        name,
        target_commit,
        target_version=target_version,
        created_by=created_by,
        target=frozen_target,
        policy=dict(policy or {}),
        strategy=normalized_strategy,
        deployment_id=deployment_id,
        now=ts,
    )
    for phase, phase_devices in phases.items():
        for device in phase_devices:
            inventory = store.get_device(device) or {}
            store.add_deployment_execution(
                did,
                device,
                phase=phase,
                state='queued',
                target_commit=target_commit,
                previous_commit=inventory.get('current_commit'),
                now=ts,
            )
            store.update_device_inventory(device, desired_commit=target_commit, now=ts)
    return {
        'deployment_id': did,
        'target_commit': store._normalize_commit(target_commit),
        'target_version': target_version,
        'target': frozen_target,
        'strategy': normalized_strategy,
        'phases': phases,
    }


def dispatch_phase(store: Any, deployment_id: str, phase: int, *, deadline_at: float | None = None, now: float | None = None) -> list[str]:
    ts = time.time() if now is None else float(now)
    deployment = store.get_deployment(deployment_id)
    if not deployment:
        raise KeyError(deployment_id)
    if str(deployment.get('state') or '') in {'paused', 'canceled', 'failed', 'succeeded'}:
        raise StrategyError(f"deployment is {deployment.get('state')}")
    phase = int(phase)
    executions = [row for row in store.list_deployment_executions(deployment_id) if int(row.get('phase') or 0) == phase]
    if not executions:
        raise StrategyError(f'phase {phase} does not exist')
    created: list[str] = []
    for row in executions:
        if row.get('command_id'):
            continue
        device = str(row['device_id'])
        command_id = store.create_command(
            device,
            'lghs-update',
            payload={'target_commit': deployment['target_commit'], 'deployment_id': deployment_id, 'phase': phase},
            deadline_at=deadline_at,
            now=ts,
            dedupe=False,
        )
        with store.transaction() as db:
            db.execute(
                '''UPDATE deployment_executions SET command_id=?,stage='Waiting for device',updated_at=? WHERE deployment_id=? AND device_id=?''',
                (command_id, ts, deployment_id, device),
            )
        created.append(command_id)
    with store.transaction() as db:
        db.execute(
            "UPDATE deployments SET state='running',started_at=COALESCE(started_at,?),updated_at=? WHERE deployment_id=?",
            (ts, ts, deployment_id),
        )
    return created


def _strategy_for(deployment: Mapping[str, Any]) -> dict[str, Any]:
    try:
        raw = json.loads(str(deployment.get('strategy_json') or '{}'))
    except Exception:
        raw = {}
    return dict(raw) if isinstance(raw, dict) else {}


def phase_gate(store: Any, deployment_id: str, phase: int) -> dict[str, Any]:
    deployment = store.get_deployment(deployment_id)
    if not deployment:
        raise KeyError(deployment_id)
    strategy = _strategy_for(deployment)
    rows = [row for row in store.list_deployment_executions(deployment_id) if int(row.get('phase') or 0) == int(phase)]
    if not rows:
        raise StrategyError(f'phase {phase} does not exist')
    failures: list[str] = []
    pending: list[str] = []
    verified: list[str] = []
    health_blocked: list[str] = []
    target = str(deployment['target_commit'])
    require_health = str(strategy.get('require_health') or 'healthy').lower()
    allowed_health = {'healthy'} if require_health == 'healthy' else {'healthy', 'warning'}
    for row in rows:
        device = str(row['device_id'])
        state = str(row.get('state') or 'queued').lower()
        inventory = store.get_device(device) or {}
        if state in FAILURE_STATES:
            failures.append(device)
            continue
        if state in OPEN_STATES or not row.get('command_id'):
            pending.append(device)
            continue
        if state != 'succeeded' or str(inventory.get('current_commit') or '').lower() != target.lower():
            pending.append(device)
            continue
        health = str(inventory.get('health_state') or 'unknown').lower()
        if health not in allowed_health:
            health_blocked.append(device)
            continue
        verified.append(device)
    failure_count = len(failures)
    failure_rate = (100.0 * failure_count / len(rows)) if rows else 0.0
    if int(phase) == 0 and strategy.get('type') == 'phased' and failures:
        state = 'paused'
        reason = 'canary failure'
    elif failures and (
        failure_count >= int(strategy.get('failure_threshold_count') or 2)
        or failure_rate >= float(strategy.get('failure_threshold_percent') or 10.0)
    ):
        state = 'paused'
        reason = 'failure threshold exceeded'
    elif pending:
        state = 'waiting'
        reason = 'phase still executing or awaiting commit verification'
    elif health_blocked:
        state = 'waiting'
        reason = 'post-update health gate not satisfied'
    else:
        state = 'ready'
        reason = 'phase complete and health verified'
    return {
        'deployment_id': deployment_id,
        'phase': int(phase),
        'state': state,
        'reason': reason,
        'total': len(rows),
        'verified': verified,
        'failed': failures,
        'pending': pending,
        'health_blocked': health_blocked,
        'failure_rate': round(failure_rate, 2),
    }


def rollout_status(store: Any, deployment_id: str) -> dict[str, Any]:
    deployment = store.get_deployment(deployment_id)
    if not deployment:
        raise KeyError(deployment_id)
    rows = store.list_deployment_executions(deployment_id)
    phases = sorted({int(row.get('phase') or 0) for row in rows})
    gates = [phase_gate(store, deployment_id, phase) for phase in phases]
    dispatched = [phase for phase in phases if any(row.get('command_id') for row in rows if int(row.get('phase') or 0) == phase)]
    active_phase = max(dispatched) if dispatched else None
    next_phase = None
    if active_phase is None:
        next_phase = phases[0] if phases else None
    else:
        gate = next(item for item in gates if item['phase'] == active_phase)
        later = [phase for phase in phases if phase > active_phase]
        if gate['state'] == 'ready' and later:
            next_phase = later[0]
    return {
        'deployment': deployment,
        'active_phase': active_phase,
        'next_phase': next_phase,
        'phases': gates,
    }


def advance_rollout(store: Any, deployment_id: str, *, deadline_at: float | None = None, now: float | None = None) -> dict[str, Any]:
    status = rollout_status(store, deployment_id)
    active = status['active_phase']
    if active is not None:
        gate = next(item for item in status['phases'] if item['phase'] == active)
        if gate['state'] == 'paused':
            with store.transaction() as db:
                db.execute("UPDATE deployments SET state='paused',paused_reason=?,updated_at=? WHERE deployment_id=?", (gate['reason'], time.time() if now is None else float(now), deployment_id))
            return rollout_status(store, deployment_id)
        if gate['state'] != 'ready':
            raise StrategyError(gate['reason'])
    phase = status['next_phase']
    if phase is None:
        if status['phases'] and all(item['state'] == 'ready' for item in status['phases']):
            with store.transaction() as db:
                ts = time.time() if now is None else float(now)
                db.execute("UPDATE deployments SET state='succeeded',completed_at=COALESCE(completed_at,?),updated_at=? WHERE deployment_id=?", (ts, ts, deployment_id))
        return rollout_status(store, deployment_id)
    dispatch_phase(store, deployment_id, phase, deadline_at=deadline_at, now=now)
    return rollout_status(store, deployment_id)
