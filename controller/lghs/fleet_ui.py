'''Pure helpers for Fleet Control deployment creation and filtering.'''
from __future__ import annotations

import re
import shlex
from typing import Any, Mapping

HEX40 = re.compile(r'^[0-9a-fA-F]{40}$')


def _text(value: Any) -> str:
    return str(value or '').strip()


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {'1', 'true', 'yes', 'on', 'y'}


def _selector(row: Mapping[str, Any]) -> dict[str, Any]:
    target = row.get('target', {}) if isinstance(row.get('target'), Mapping) else {}
    selector = target.get('selector', {}) if isinstance(target.get('selector'), Mapping) else {}
    return dict(selector)


def _resolved_devices(row: Mapping[str, Any]) -> list[str]:
    target = row.get('target', {}) if isinstance(row.get('target'), Mapping) else {}
    raw = target.get('resolved_devices', [])
    return [str(x).upper() for x in raw] if isinstance(raw, list) else []


def deployment_matches(row: Mapping[str, Any], query: str) -> bool:
    '''Match deployment list rows using whitespace-separated AND terms.

    Supported keyed terms: state:, name:, id:, target:/commit:, version:,
    device:, group:, tag:, strategy:, auto:, maintenance:. Quoted values are
    accepted through shlex (for example name:"Room 101 rollout"). Plain terms
    search the common deployment fields and frozen target membership.
    '''
    try:
        terms = shlex.split(query or '')
    except ValueError:
        terms = (query or '').split()
    if not terms:
        return True

    selector = _selector(row)
    devices = _resolved_devices(row)
    policy = row.get('policy', {}) if isinstance(row.get('policy'), Mapping) else {}
    strategy = row.get('strategy', {}) if isinstance(row.get('strategy'), Mapping) else {}
    fields = {
        'state': _text(row.get('state')).lower(),
        'name': _text(row.get('name')).lower(),
        'id': _text(row.get('deployment_id')).lower(),
        'target': _text(row.get('target_commit')).lower(),
        'commit': _text(row.get('target_commit')).lower(),
        'version': _text(row.get('target_version')).lower(),
        'strategy': _text(strategy.get('type')).lower(),
        'group': _text(selector.get('group_id')).lower(),
        'tag': _text(selector.get('tag')).lower(),
    }
    haystack = ' '.join([
        fields['state'], fields['name'], fields['id'], fields['target'],
        fields['version'], fields['strategy'], fields['group'], fields['tag'],
        ' '.join(devices).lower(),
    ])

    for term in terms:
        if ':' not in term:
            if term.lower() not in haystack:
                return False
            continue
        key, value = term.split(':', 1)
        key = key.strip().lower()
        value = value.strip().lower()
        if key == 'device':
            if not any(value in device.lower() for device in devices):
                return False
        elif key == 'auto':
            if bool(policy.get('auto_advance')) != _bool(value):
                return False
        elif key in {'maintenance', 'maint'}:
            if bool(policy.get('respect_maintenance')) != _bool(value):
                return False
        elif key in fields:
            if value not in fields[key]:
                return False
        else:
            return False
    return True


def filter_deployments(rows: list[Mapping[str, Any]], query: str) -> list[Mapping[str, Any]]:
    return [row for row in rows if deployment_matches(row, query)]


def build_create_args(spec: Mapping[str, Any]) -> list[str]:
    name = _text(spec.get('name'))
    if not name:
        raise ValueError('deployment name is required')
    commit = _text(spec.get('target_commit')).lower()
    if not HEX40.fullmatch(commit):
        raise ValueError('target commit must be an exact 40-character Git SHA')
    target_type = _text(spec.get('target_type')).lower()
    target_value = _text(spec.get('target_value'))
    target_args: list[str]
    if target_type == 'device':
        if not target_value:
            raise ValueError('device target is required')
        target_args = ['--device', target_value.upper()]
    elif target_type == 'group':
        if not target_value:
            raise ValueError('group target is required')
        target_args = ['--group', target_value]
    elif target_type == 'tag':
        if not target_value:
            raise ValueError('tag target is required')
        target_args = ['--tag', target_value.lower()]
    elif target_type == 'all':
        target_args = ['--all']
    else:
        raise ValueError('target type must be device, group, tag, or all')

    args = ['create', '--name', name, '--target-commit', commit, *target_args]
    version = _text(spec.get('target_version'))
    if version:
        args += ['--target-version', version]

    try:
        health_age = int(spec.get('health_max_age', 45))
    except Exception as exc:
        raise ValueError('health max age must be an integer') from exc
    if health_age < 10 or health_age > 600:
        raise ValueError('health max age must be between 10 and 600 seconds')
    args += ['--health-max-age', str(health_age)]

    if _bool(spec.get('phased')):
        try:
            canary = int(spec.get('canary_count', 1))
            soak = int(spec.get('soak_seconds', 300))
        except Exception as exc:
            raise ValueError('canary count and soak seconds must be integers') from exc
        waves = _text(spec.get('waves')) or '20,50,100'
        if canary < 1 or soak < 0:
            raise ValueError('canary count must be >=1 and soak seconds must be >=0')
        args += ['--phased', '--canary-count', str(canary), '--waves', waves, '--soak-seconds', str(soak)]
        canary_tag = _text(spec.get('canary_tag'))
        if canary_tag:
            args += ['--canary-tag', canary_tag.lower()]

    required = spec.get('required_health_checks', [])
    if required:
        if not isinstance(required, (list, tuple)):
            raise ValueError('required health checks must be a list')
        for check_id in required:
            value = _text(check_id)
            if not value:
                raise ValueError('required health check cannot be empty')
            args += ['--required-health-check', value]

    if _bool(spec.get('respect_maintenance')):
        args.append('--respect-maintenance')
    if _bool(spec.get('auto')):
        args.append('--auto')
    elif _bool(spec.get('dispatch')):
        args.append('--dispatch')
    return args
