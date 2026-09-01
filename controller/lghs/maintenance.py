'''Maintenance-window policy and reboot scheduling for LGHS 0.6.'''
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .protocol import normalize_device_id
from .rollout import resolve_targets

MAINTENANCE_PREFIX = 'maintenance:'
REBOOT_PREFIX = 'reboot-schedule:'
DAY_NAMES = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
DAY_MAP = {name: index for index, name in enumerate(DAY_NAMES)}
CANCELABLE_COMMAND_STATES = frozenset({'queued'})
FAILED_COMMAND_STATES = frozenset({'failed', 'timed_out', 'rejected', 'canceled'})
TERMINAL_REBOOT_STATES = frozenset({'succeeded', 'failed', 'canceled'})


class MaintenanceError(ValueError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def _actor(value: Any) -> str:
    text = str(value or 'unknown').strip()
    return text[:128] or 'unknown'


def controller_timezone() -> str:
    configured = str(os.environ.get('LGHS_TIMEZONE') or '').strip()
    if configured:
        return configured
    try:
        value = Path('/etc/timezone').read_text(encoding='utf-8').strip()
        if value:
            return value
    except Exception:
        pass
    return 'UTC'


def _timezone(value: Any) -> str:
    name = str(value or controller_timezone()).strip()
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise MaintenanceError(f'unknown timezone: {name}') from exc
    return name


def _hhmm(value: Any) -> tuple[str, int]:
    text = str(value or '').strip()
    parts = text.split(':')
    if len(parts) != 2:
        raise MaintenanceError('time must use HH:MM')
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise MaintenanceError('time must use HH:MM') from exc
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise MaintenanceError('time must use 24-hour HH:MM')
    return f'{hour:02d}:{minute:02d}', hour * 60 + minute


def _days(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple, set)) or not value:
        raise MaintenanceError('window days must be a non-empty list')
    out: set[int] = set()
    for item in value:
        if isinstance(item, int):
            day = item
        else:
            text = str(item).strip().lower()[:3]
            if text not in DAY_MAP:
                raise MaintenanceError(f'invalid day: {item}')
            day = DAY_MAP[text]
        if day < 0 or day > 6:
            raise MaintenanceError(f'invalid day: {item}')
        out.add(day)
    return sorted(out)


def normalize_policy(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise MaintenanceError('maintenance policy must be an object')
    enabled = bool(raw.get('enabled', True))
    timezone_name = _timezone(raw.get('timezone'))
    windows_raw = raw.get('windows')
    if not isinstance(windows_raw, (list, tuple)) or not windows_raw:
        raise MaintenanceError('maintenance policy requires at least one window')
    windows: list[dict[str, Any]] = []
    for item in windows_raw:
        if not isinstance(item, Mapping):
            raise MaintenanceError('maintenance window must be an object')
        start, start_minute = _hhmm(item.get('start'))
        end, end_minute = _hhmm(item.get('end'))
        if start_minute == end_minute:
            raise MaintenanceError('maintenance window start and end cannot be equal')
        windows.append({'days': _days(item.get('days')), 'start': start, 'end': end})
    return {'enabled': enabled, 'timezone': timezone_name, 'windows': windows}


def _minute(value: str) -> int:
    hour, minute = value.split(':', 1)
    return int(hour) * 60 + int(minute)


def _policy_open(policy: Mapping[str, Any], epoch: float) -> bool:
    zone = ZoneInfo(str(policy['timezone']))
    current = datetime.fromtimestamp(float(epoch), zone)
    weekday = current.weekday()
    minute = current.hour * 60 + current.minute
    previous_day = (weekday - 1) % 7
    for window in policy.get('windows', []):
        start = _minute(str(window['start']))
        end = _minute(str(window['end']))
        days = {int(day) for day in window.get('days', [])}
        if start < end:
            if weekday in days and start <= minute < end:
                return True
        else:
            if weekday in days and minute >= start:
                return True
            if previous_day in days and minute < end:
                return True
    return False


def _setting(store: Any, key: str) -> dict[str, Any] | None:
    with store.connect() as db:
        row = db.execute('SELECT value_json FROM settings WHERE key=?', (key,)).fetchone()
    if not row:
        return None
    try:
        value = json.loads(str(row['value_json'] or '{}'))
    except Exception:
        return None
    return dict(value) if isinstance(value, dict) else None


def _save_setting(store: Any, key: str, value: Mapping[str, Any], *, now: float) -> None:
    with store.transaction() as db:
        db.execute(
            '''INSERT INTO settings(key,value_json,updated_at) VALUES(?,?,?)
               ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
            (key, _json(dict(value)), now),
        )


def _delete_setting(store: Any, key: str) -> None:
    with store.transaction() as db:
        db.execute('DELETE FROM settings WHERE key=?', (key,))


def _audit(store: Any, kind: str, actor: str, detail: Mapping[str, Any], *, device_id: str | None = None, now: float) -> None:
    payload = dict(detail)
    payload['actor'] = _actor(actor)
    with store.transaction() as db:
        db.execute(
            'INSERT INTO audit_events(device_id,kind,severity,created_at,sequence,detail_json) VALUES(?,?,?,?,?,?)',
            (device_id, kind, 'info', now, None, _json(payload)),
        )


def set_device_policy(store: Any, device_id: str, policy: Mapping[str, Any], *, actor: str = 'unknown', now: float | None = None) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    device = normalize_device_id(device_id)
    if not store.get_device(device):
        raise KeyError(device)
    normalized = normalize_policy(policy)
    _save_setting(store, MAINTENANCE_PREFIX + 'device:' + device, normalized, now=ts)
    _audit(store, 'maintenance-policy', actor, {'scope': 'device', 'device_id': device, 'policy': normalized}, device_id=device, now=ts)
    return normalized


def set_group_policy(store: Any, group_id: str, policy: Mapping[str, Any], *, actor: str = 'unknown', now: float | None = None) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    group = str(group_id or '').strip().lower()
    if not group:
        raise MaintenanceError('group_id is required')
    if not any(str(row.get('group_id')) == group for row in store.list_groups()):
        raise KeyError(group)
    normalized = normalize_policy(policy)
    _save_setting(store, MAINTENANCE_PREFIX + 'group:' + group, normalized, now=ts)
    _audit(store, 'maintenance-policy', actor, {'scope': 'group', 'group_id': group, 'policy': normalized}, now=ts)
    return normalized


def clear_device_policy(store: Any, device_id: str, *, actor: str = 'unknown', now: float | None = None) -> None:
    ts = time.time() if now is None else float(now)
    device = normalize_device_id(device_id)
    _delete_setting(store, MAINTENANCE_PREFIX + 'device:' + device)
    _audit(store, 'maintenance-policy', actor, {'scope': 'device', 'device_id': device, 'cleared': True}, device_id=device, now=ts)


def clear_group_policy(store: Any, group_id: str, *, actor: str = 'unknown', now: float | None = None) -> None:
    ts = time.time() if now is None else float(now)
    group = str(group_id or '').strip().lower()
    _delete_setting(store, MAINTENANCE_PREFIX + 'group:' + group)
    _audit(store, 'maintenance-policy', actor, {'scope': 'group', 'group_id': group, 'cleared': True}, now=ts)


def list_policies(store: Any) -> list[dict[str, Any]]:
    with store.connect() as db:
        rows = db.execute('SELECT key,value_json,updated_at FROM settings WHERE key LIKE ? ORDER BY key', (MAINTENANCE_PREFIX + '%',)).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = str(row['key'])
        try:
            policy = json.loads(str(row['value_json']))
        except Exception:
            policy = {}
        scope, identifier = key[len(MAINTENANCE_PREFIX):].split(':', 1)
        out.append({'scope': scope, 'id': identifier, 'policy': policy, 'updated_at': row['updated_at']})
    return out


def effective_policies(store: Any, device_id: str) -> list[dict[str, Any]]:
    device = normalize_device_id(device_id)
    direct = _setting(store, MAINTENANCE_PREFIX + 'device:' + device)
    if direct is not None:
        if not bool(direct.get('enabled', True)):
            return []
        return [{'scope': 'device', 'id': device, 'policy': direct}]
    policies: list[dict[str, Any]] = []
    for group in store.list_groups(device):
        group_id = str(group['group_id'])
        policy = _setting(store, MAINTENANCE_PREFIX + 'group:' + group_id)
        if policy is not None and bool(policy.get('enabled', True)):
            policies.append({'scope': 'group', 'id': group_id, 'policy': policy})
    return policies


def maintenance_state(store: Any, device_id: str, *, now: float | None = None, horizon_days: int = 21) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    device = normalize_device_id(device_id)
    policies = effective_policies(store, device)
    if not policies:
        return {'device_id': device, 'allowed': True, 'managed': False, 'policies': [], 'next_open_at': ts, 'reason': 'no active maintenance policy'}

    def open_at(epoch: float) -> bool:
        return all(_policy_open(item['policy'], epoch) for item in policies)

    allowed = open_at(ts)
    next_open = ts if allowed else None
    if next_open is None:
        probe = (int(ts) // 60 + 1) * 60
        limit = probe + max(1, int(horizon_days)) * 86400
        while probe <= limit:
            if open_at(probe):
                next_open = float(probe)
                break
            probe += 60
    reason = 'maintenance window open' if allowed else 'outside maintenance window'
    if next_open is None:
        reason = 'no overlapping maintenance window in search horizon'
    return {
        'device_id': device,
        'allowed': allowed,
        'managed': True,
        'policies': policies,
        'next_open_at': next_open,
        'reason': reason,
    }


def phase_maintenance_gate(store: Any, deployment_id: str, phase: int, *, now: float | None = None) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    rows = [row for row in store.list_deployment_executions(deployment_id) if int(row.get('phase') or 0) == int(phase)]
    if not rows:
        raise KeyError(f'phase:{phase}')
    states = [maintenance_state(store, str(row['device_id']), now=ts) for row in rows]
    blocked = [row for row in states if not row['allowed']]
    next_values = [float(row['next_open_at']) for row in blocked if row.get('next_open_at') is not None]
    return {
        'deployment_id': deployment_id,
        'phase': int(phase),
        'allowed': not blocked,
        'blocked_devices': [row['device_id'] for row in blocked],
        'next_open_at': max(next_values) if next_values and len(next_values) == len(blocked) else None,
        'devices': states,
    }


def _schedule_key(schedule_id: str) -> str:
    return REBOOT_PREFIX + str(schedule_id)


def create_reboot_schedule(
    store: Any,
    *,
    selector: Mapping[str, Any],
    mode: str = 'at',
    scheduled_at: float | None = None,
    not_before: float | None = None,
    created_by: str = 'unknown',
    reason: str = '',
    verify_timeout_seconds: int = 1800,
    schedule_id: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    normalized_selector, devices = resolve_targets(store, selector)
    mode_name = str(mode or 'at').strip().lower()
    if mode_name not in {'at', 'maintenance'}:
        raise MaintenanceError('reboot mode must be at or maintenance')
    if mode_name == 'at':
        due = ts if scheduled_at is None else float(scheduled_at)
        if due < ts - 60:
            raise MaintenanceError('scheduled_at is too far in the past')
    else:
        due = None
    floor = ts if not_before is None else float(not_before)
    timeout = max(60, min(int(verify_timeout_seconds), 86400))
    executions: dict[str, Any] = {}
    for device in devices:
        inventory = store.get_device(device) or {}
        boot = str(inventory.get('boot_id') or '').strip()
        if not boot:
            raise MaintenanceError(f'{device} has no reported boot_id; cannot verify reboot')
        executions[device] = {
            'device_id': device,
            'state': 'queued',
            'boot_id_before': boot,
            'command_id': None,
            'created_at': ts,
            'updated_at': ts,
        }
    sid = str(schedule_id or ('reboot-' + uuid.uuid4().hex[:16])).strip()
    if not sid or len(sid) > 96:
        raise MaintenanceError('invalid reboot schedule id')
    schedule = {
        'schedule_id': sid,
        'mode': mode_name,
        'selector': normalized_selector,
        'resolved_devices': devices,
        'scheduled_at': due,
        'not_before': floor,
        'verify_timeout_seconds': timeout,
        'created_by': _actor(created_by),
        'reason': str(reason or '')[:500],
        'state': 'queued',
        'created_at': ts,
        'updated_at': ts,
        'executions': executions,
    }
    if _setting(store, _schedule_key(sid)) is not None:
        raise MaintenanceError('reboot schedule id already exists')
    _save_setting(store, _schedule_key(sid), schedule, now=ts)
    _audit(store, 'reboot-schedule', created_by, {'action': 'created', 'schedule_id': sid, 'mode': mode_name, 'devices': devices, 'scheduled_at': due, 'not_before': floor}, now=ts)
    return schedule


def get_reboot_schedule(store: Any, schedule_id: str) -> dict[str, Any] | None:
    return _setting(store, _schedule_key(schedule_id))


def list_reboot_schedules(store: Any) -> list[dict[str, Any]]:
    with store.connect() as db:
        rows = db.execute('SELECT value_json FROM settings WHERE key LIKE ? ORDER BY updated_at DESC', (REBOOT_PREFIX + '%',)).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            value = json.loads(str(row['value_json']))
        except Exception:
            continue
        if isinstance(value, dict):
            out.append(value)
    return out


def cancel_reboot_schedule(store: Any, schedule_id: str, *, actor: str = 'unknown', now: float | None = None) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    schedule = get_reboot_schedule(store, schedule_id)
    if not schedule:
        raise KeyError(schedule_id)
    if str(schedule.get('state') or '') in TERMINAL_REBOOT_STATES:
        raise MaintenanceError(f"reboot schedule is {schedule.get('state')}")
    continuing: list[str] = []
    canceled: list[str] = []
    executions = dict(schedule.get('executions') or {})
    for device, row_raw in executions.items():
        row = dict(row_raw or {})
        if str(row.get('state') or '') in TERMINAL_REBOOT_STATES:
            continue
        command_id = row.get('command_id')
        if command_id:
            command = store.get_command(str(command_id)) or {}
            command_state = str(command.get('state') or '').lower()
            if command_state in CANCELABLE_COMMAND_STATES:
                store.transition_command(str(command_id), 'canceled', stage='Scheduled reboot canceled', message='Canceled before delivery to device', now=ts, detail={'schedule_id': schedule_id, 'actor': _actor(actor)})
                row.update({'state': 'canceled', 'updated_at': ts, 'completed_at': ts, 'message': 'Canceled before delivery'})
                canceled.append(device)
            else:
                continuing.append(device)
        else:
            row.update({'state': 'canceled', 'updated_at': ts, 'completed_at': ts, 'message': 'Canceled before dispatch'})
            canceled.append(device)
        executions[device] = row
    schedule['executions'] = executions
    schedule['state'] = 'canceling' if continuing else 'canceled'
    schedule['updated_at'] = ts
    schedule['canceled_at'] = ts
    _save_setting(store, _schedule_key(schedule_id), schedule, now=ts)
    _audit(store, 'reboot-schedule', actor, {'action': 'cancel', 'schedule_id': schedule_id, 'canceled_devices': canceled, 'continuing_devices': continuing}, now=ts)
    return {'schedule_id': schedule_id, 'state': schedule['state'], 'canceled_devices': canceled, 'continuing_devices': continuing}


def _dispatch_reboot(store: Any, schedule: dict[str, Any], device: str, *, now: float) -> str:
    return store.create_command(
        device,
        'reboot',
        payload={'schedule_id': schedule['schedule_id'], 'reason': schedule.get('reason') or ''},
        deadline_at=now + 300,
        now=now,
        dedupe=False,
    )


def _execution_audit(store: Any, schedule: Mapping[str, Any], device: str, action: str, detail: Mapping[str, Any], *, now: float) -> None:
    payload = {'schedule_id': schedule.get('schedule_id'), 'action': action, **dict(detail)}
    _audit(store, 'reboot-execution', 'rollout-manager', payload, device_id=device, now=now)


def reconcile_reboot_schedule(store: Any, schedule_id: str, *, now: float | None = None) -> dict[str, Any]:
    ts = time.time() if now is None else float(now)
    schedule = get_reboot_schedule(store, schedule_id)
    if not schedule:
        raise KeyError(schedule_id)
    state = str(schedule.get('state') or 'queued')
    if state in TERMINAL_REBOOT_STATES:
        return {'schedule_id': schedule_id, 'action': 'terminal', 'state': state}
    canceling = state == 'canceling'
    changed = False
    actions: list[dict[str, Any]] = []
    executions = dict(schedule.get('executions') or {})
    for device, row_raw in list(executions.items()):
        row = dict(row_raw or {})
        row_state = str(row.get('state') or 'queued')
        if row_state in TERMINAL_REBOOT_STATES:
            continue
        inventory = store.get_device(device) or {}
        boot_now = str(inventory.get('boot_id') or '').strip()
        command_id = row.get('command_id')
        if command_id:
            command = store.get_command(str(command_id)) or {}
            command_state = str(command.get('state') or '').lower()
            if boot_now and boot_now != str(row.get('boot_id_before') or ''):
                if command and command_state != 'succeeded':
                    try:
                        store.transition_command(str(command_id), 'succeeded', stage='Reboot verified', message='Device returned with a new boot_id', progress=100, now=ts, detail={'schedule_id': schedule_id, 'boot_id': boot_now})
                    except ValueError:
                        pass
                row.update({'state': 'succeeded', 'updated_at': ts, 'completed_at': ts, 'boot_id_after': boot_now, 'message': 'Reboot verified by boot_id change'})
                executions[device] = row
                changed = True
                action = {'device_id': device, 'action': 'verified'}
                actions.append(action)
                _execution_audit(store, schedule, device, 'verified', {'boot_id_before': row.get('boot_id_before'), 'boot_id_after': boot_now, 'command_id': command_id}, now=ts)
                continue
            if command_state in FAILED_COMMAND_STATES:
                row.update({'state': 'failed', 'updated_at': ts, 'completed_at': ts, 'message': f'reboot command {command_state}'})
                executions[device] = row
                changed = True
                actions.append({'device_id': device, 'action': 'failed', 'reason': command_state})
                _execution_audit(store, schedule, device, 'failed', {'reason': command_state, 'command_id': command_id}, now=ts)
                continue
            dispatched_at = float(row.get('dispatched_at') or ts)
            if ts - dispatched_at > int(schedule.get('verify_timeout_seconds') or 1800):
                row.update({'state': 'failed', 'updated_at': ts, 'completed_at': ts, 'message': 'reboot verification timed out'})
                executions[device] = row
                changed = True
                actions.append({'device_id': device, 'action': 'failed', 'reason': 'verification-timeout'})
                _execution_audit(store, schedule, device, 'failed', {'reason': 'verification-timeout', 'command_id': command_id}, now=ts)
                continue
            if command_state in {'accepted', 'running'} and row_state != 'reboot_pending':
                row.update({'state': 'reboot_pending', 'updated_at': ts, 'message': 'Reboot accepted locally; waiting for boot_id change'})
                changed = True
                actions.append({'device_id': device, 'action': 'reboot-pending'})
                _execution_audit(store, schedule, device, 'reboot-pending', {'command_id': command_id}, now=ts)
            executions[device] = row
            continue

        if canceling:
            continue
        if ts < float(schedule.get('not_before') or 0):
            continue
        mode = str(schedule.get('mode') or 'at')
        if mode == 'at':
            if ts < float(schedule.get('scheduled_at') or 0):
                continue
        elif not maintenance_state(store, device, now=ts)['allowed']:
            continue
        if not boot_now:
            if row.get('message') != 'Waiting for current boot_id before dispatch':
                row.update({'state': 'queued', 'updated_at': ts, 'message': 'Waiting for current boot_id before dispatch'})
                executions[device] = row
                changed = True
                actions.append({'device_id': device, 'action': 'waiting-for-boot-id'})
            continue
        row['boot_id_before'] = boot_now
        command_id = _dispatch_reboot(store, schedule, device, now=ts)
        row.update({'state': 'dispatched', 'command_id': command_id, 'dispatched_at': ts, 'updated_at': ts, 'message': 'Reboot command dispatched'})
        executions[device] = row
        changed = True
        actions.append({'device_id': device, 'action': 'dispatched', 'command_id': command_id, 'boot_id_before': boot_now})
        _execution_audit(store, schedule, device, 'dispatched', {'command_id': command_id, 'boot_id_before': boot_now}, now=ts)

    schedule['executions'] = executions
    states = [str(row.get('state') or '') for row in executions.values()]
    if states and all(value == 'succeeded' for value in states):
        schedule['state'] = 'succeeded'
        schedule['completed_at'] = ts
        changed = True
    elif canceling and states and all(value in TERMINAL_REBOOT_STATES for value in states):
        schedule['state'] = 'canceled'
        schedule['completed_at'] = ts
        changed = True
    elif states and all(value in TERMINAL_REBOOT_STATES for value in states) and any(value == 'failed' for value in states):
        schedule['state'] = 'failed'
        schedule['completed_at'] = ts
        changed = True
    elif any(value in {'dispatched', 'reboot_pending'} for value in states):
        schedule['state'] = 'running' if not canceling else 'canceling'
    schedule['updated_at'] = ts
    if changed:
        _save_setting(store, _schedule_key(schedule_id), schedule, now=ts)
    return {'schedule_id': schedule_id, 'action': 'reconciled', 'state': schedule.get('state'), 'actions': actions, 'schedule': schedule}


def reconcile_reboot_schedules(store: Any, *, now: float | None = None) -> list[dict[str, Any]]:
    ts = time.time() if now is None else float(now)
    results: list[dict[str, Any]] = []
    for schedule in list_reboot_schedules(store):
        if str(schedule.get('state') or '') in TERMINAL_REBOOT_STATES:
            continue
        schedule_id = str(schedule.get('schedule_id') or '')
        if not schedule_id:
            continue
        try:
            results.append(reconcile_reboot_schedule(store, schedule_id, now=ts))
        except Exception as exc:
            results.append({'schedule_id': schedule_id, 'action': 'error', 'error': str(exc)})
    return results
