'''Operator recovery controls for LGHS 0.6 deployments.'''
from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Any

from .rollout import StrategyError, dispatch_phase, freeze_deployment, rollout_status
from .rollout_manager import load_runtime, save_runtime

RETRYABLE_STATES = frozenset({'failed', 'timed_out', 'rejected'})
CANCELABLE_COMMAND_STATES = frozenset({'queued', 'delivered', 'received'})
TERMINAL_DEPLOYMENT_STATES = frozenset({'canceled', 'succeeded'})


def _actor(value: Any) -> str:
    text = str(value or 'unknown').strip()
    return text[:128] or 'unknown'


def _audit(store: Any, deployment_id: str, action: str, actor: str, detail: dict[str, Any], *, now: float) -> None:
    payload = dict(detail)
    payload.update({'deployment_id': deployment_id, 'action': action, 'actor': _actor(actor)})
    with store.transaction() as db:
        db.execute(
            'INSERT INTO audit_events(device_id,kind,severity,created_at,sequence,detail_json) VALUES(NULL,?,?,?,?,?)',
            ('deployment', 'info', now, None, json.dumps(payload, sort_keys=True, separators=(',', ':'))),
        )


def _reset_runtime(store: Any, deployment_id: str, *, now: float, note: str) -> dict[str, Any]:
    runtime = load_runtime(store, deployment_id)
    runtime['ready_since'] = None
    runtime['next_action_at'] = None
    runtime['paused_reason'] = None
    runtime['recovery_at'] = now
    runtime['recovery_note'] = note
    save_runtime(store, deployment_id, runtime, now=now)
    return runtime


def retry_failed(store: Any, deployment_id: str, *, actor: str = 'unknown', now: float | None = None) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    deployment = store.get_deployment(deployment_id)
    if not deployment:
        raise KeyError(deployment_id)
    if str(deployment.get('state') or '').lower() in TERMINAL_DEPLOYMENT_STATES:
        raise StrategyError(f"deployment is {deployment.get('state')}")
    rows = store.list_deployment_executions(deployment_id)
    retryable = [row for row in rows if str(row.get('state') or '').lower() in RETRYABLE_STATES]
    if not retryable:
        raise StrategyError('deployment has no retryable failed executions')

    commands: list[str] = []
    devices: list[str] = []
    for row in retryable:
        device = str(row['device_id'])
        target_commit = store._normalize_commit(row.get('target_commit') or deployment['target_commit'])
        attempt = int(row.get('attempt') or 0) + 1
        command_id = store.create_command(
            device,
            'lghs-update',
            payload={
                'target_commit': target_commit,
                'deployment_id': deployment_id,
                'phase': int(row.get('phase') or 0),
                'attempt': attempt,
                'retry_of': row.get('command_id'),
            },
            now=ts,
            dedupe=False,
        )
        with store.transaction() as db:
            db.execute(
                '''UPDATE deployment_executions
                   SET command_id=?,state='queued',stage='Retry queued',attempt=?,started_at=NULL,completed_at=NULL,
                       error_code=NULL,error_message='',updated_at=?
                   WHERE deployment_id=? AND device_id=?''',
                (command_id, attempt, ts, deployment_id, device),
            )
        store.update_device_inventory(device, desired_commit=target_commit, now=ts)
        commands.append(command_id)
        devices.append(device)

    with store.transaction() as db:
        db.execute(
            "UPDATE deployments SET state='running',paused_reason='',completed_at=NULL,started_at=COALESCE(started_at,?),updated_at=? WHERE deployment_id=?",
            (ts, ts, deployment_id),
        )
    runtime = _reset_runtime(store, deployment_id, now=ts, note='retry-failed')
    _audit(store, deployment_id, 'retry-failed', actor, {'devices': devices, 'command_ids': commands}, now=ts)
    return {'deployment_id': deployment_id, 'action': 'retry-failed', 'devices': devices, 'command_ids': commands, 'runtime': runtime}


def resume_deployment(store: Any, deployment_id: str, *, actor: str = 'unknown', now: float | None = None) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    deployment = store.get_deployment(deployment_id)
    if not deployment:
        raise KeyError(deployment_id)
    if str(deployment.get('state') or '').lower() != 'paused':
        raise StrategyError('deployment is not paused')
    status = rollout_status(store, deployment_id)
    active = status.get('active_phase')
    if active is not None:
        gate = next(item for item in status['phases'] if item['phase'] == active)
        if gate.get('state') == 'paused':
            raise StrategyError('pause condition is still active; retry failed executions before continuing')
    with store.transaction() as db:
        db.execute("UPDATE deployments SET state='running',paused_reason='',updated_at=? WHERE deployment_id=?", (ts, deployment_id))
    runtime = _reset_runtime(store, deployment_id, now=ts, note='resume')
    _audit(store, deployment_id, 'resume', actor, {'active_phase': active}, now=ts)
    return {'deployment_id': deployment_id, 'action': 'resumed', 'status': rollout_status(store, deployment_id), 'runtime': runtime}


def cancel_remaining(store: Any, deployment_id: str, *, actor: str = 'unknown', now: float | None = None) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    deployment = store.get_deployment(deployment_id)
    if not deployment:
        raise KeyError(deployment_id)
    if str(deployment.get('state') or '').lower() == 'succeeded':
        raise StrategyError('cannot cancel a succeeded deployment')

    canceled: list[str] = []
    continuing: list[str] = []
    for row in store.list_deployment_executions(deployment_id):
        device = str(row['device_id'])
        state = str(row.get('state') or '').lower()
        command_id = row.get('command_id')
        if command_id:
            command = store.get_command(str(command_id)) or {}
            command_state = str(command.get('state') or state).lower()
            if command_state in CANCELABLE_COMMAND_STATES:
                store.transition_command(
                    str(command_id),
                    'canceled',
                    stage='Canceled by operator',
                    message='Deployment canceled before local execution began',
                    now=ts,
                    detail={'deployment_id': deployment_id, 'actor': _actor(actor)},
                )
                with store.transaction() as db:
                    db.execute(
                        "UPDATE deployment_executions SET state='canceled',stage='Canceled by operator',completed_at=COALESCE(completed_at,?),error_code='CANCELED',error_message='Canceled before local execution began',updated_at=? WHERE deployment_id=? AND device_id=?",
                        (ts, ts, deployment_id, device),
                    )
                canceled.append(device)
            elif command_state in {'accepted', 'running'}:
                continuing.append(device)
        elif state not in {'succeeded', 'failed', 'timed_out', 'rejected', 'canceled'}:
            with store.transaction() as db:
                db.execute(
                    "UPDATE deployment_executions SET state='canceled',stage='Canceled before dispatch',completed_at=COALESCE(completed_at,?),error_code='CANCELED',error_message='Canceled before dispatch',updated_at=? WHERE deployment_id=? AND device_id=?",
                    (ts, ts, deployment_id, device),
                )
            canceled.append(device)

    with store.transaction() as db:
        db.execute(
            "UPDATE deployments SET state='canceled',paused_reason='Canceled by operator',completed_at=COALESCE(completed_at,?),updated_at=? WHERE deployment_id=?",
            (ts, ts, deployment_id),
        )
    runtime = _reset_runtime(store, deployment_id, now=ts, note='cancel-remaining')
    runtime['canceled_at'] = ts
    save_runtime(store, deployment_id, runtime, now=ts)
    _audit(store, deployment_id, 'cancel-remaining', actor, {'canceled_devices': canceled, 'continuing_devices': continuing}, now=ts)
    return {'deployment_id': deployment_id, 'action': 'canceled', 'canceled_devices': canceled, 'continuing_devices': continuing, 'runtime': runtime}


def create_rollback(
    store: Any,
    deployment_id: str,
    *,
    actor: str = 'unknown',
    dispatch: bool = False,
    auto_advance: bool = False,
    now: float | None = None,
) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    deployment = store.get_deployment(deployment_id)
    if not deployment:
        raise KeyError(deployment_id)
    groups: dict[str, list[str]] = defaultdict(list)
    skipped: dict[str, str] = {}
    for row in store.list_deployment_executions(deployment_id):
        device = str(row['device_id'])
        previous = str(row.get('previous_commit') or '').lower()
        inventory = store.get_device(device) or {}
        current = str(inventory.get('current_commit') or '').lower()
        try:
            previous = store._normalize_commit(previous)
        except ValueError:
            skipped[device] = 'no-valid-previous-commit'
            continue
        if current == previous:
            skipped[device] = 'already-at-previous-commit'
            continue
        if current != str(deployment.get('target_commit') or '').lower():
            skipped[device] = 'current-commit-does-not-match-deployment-target'
            continue
        groups[previous].append(device)
    if not groups:
        raise StrategyError('no devices are safely eligible for rollback')

    rollbacks: list[dict[str, Any]] = []
    for previous, devices in sorted(groups.items()):
        result = freeze_deployment(
            store,
            name=f"Rollback {deployment.get('name') or deployment_id} to {previous[:12]}",
            target_commit=previous,
            selector={'device_ids': sorted(devices)},
            created_by=_actor(actor),
            strategy={'type': 'all-at-once'},
            policy={'auto_advance': bool(auto_advance), 'rollback_of': deployment_id},
            now=ts,
        )
        entry = {
            'deployment_id': result['deployment_id'],
            'target_commit': previous,
            'devices': sorted(devices),
            'auto_advance': bool(auto_advance),
            'command_ids': [],
        }
        if dispatch:
            entry['command_ids'] = dispatch_phase(store, result['deployment_id'], min(result['phases']), now=ts)
        rollbacks.append(entry)
        _audit(store, result['deployment_id'], 'rollback-created', actor, {'rollback_of': deployment_id, 'devices': sorted(devices), 'target_commit': previous}, now=ts)
    _audit(store, deployment_id, 'rollback-requested', actor, {'rollbacks': [x['deployment_id'] for x in rollbacks], 'skipped': skipped}, now=ts)
    return {'deployment_id': deployment_id, 'action': 'rollback-created', 'rollbacks': rollbacks, 'skipped': skipped}
