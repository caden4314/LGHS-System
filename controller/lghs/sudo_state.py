"""Persist endpoint sudo-request snapshots in the 0.5 controller database."""
from __future__ import annotations

import json
import time
from typing import Any, Mapping

from .database import FleetDB
from .protocol import normalize_device_id

ALLOWED_STATES = {'pending', 'approved', 'denied', 'expired', 'canceled', 'failed', 'succeeded', 'unknown'}


def record_snapshot(store: FleetDB, device_id: str, rows: list[Mapping[str, Any]]) -> None:
    device = normalize_device_id(device_id)
    now = time.time()
    if not isinstance(rows, list):
        return
    with store.transaction() as db:
        store.upsert_device(device, db=db)
        for item in rows[:128]:
            if not isinstance(item, Mapping):
                continue
            request_id = str(item.get('id') or '').strip()
            if not request_id or len(request_id) > 128:
                continue
            state = str(item.get('status') or 'unknown').lower()
            if state not in ALLOWED_STATES:
                state = 'unknown'
            command = str(item.get('command') or '')[:4096]
            try:
                requested = float(item.get('requested_epoch') or now)
            except Exception:
                requested = now
            try:
                expires = float(item.get('expires_epoch') or 0) or None
            except Exception:
                expires = None
            detail = {
                key: item.get(key)
                for key in (
                    'requester', 'argv', 'cwd', 'requested_at', 'resolved_at',
                    'approved_by', 'denied_by', 'authorization',
                )
                if key in item
            }
            db.execute(
                '''
                INSERT INTO sudo_requests(
                    request_id,device_id,state,command,requested_at,updated_at,expires_at,detail_json
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(request_id) DO UPDATE SET
                    device_id=excluded.device_id,
                    state=excluded.state,
                    command=excluded.command,
                    updated_at=excluded.updated_at,
                    expires_at=excluded.expires_at,
                    detail_json=excluded.detail_json
                ''',
                (request_id, device, state, command, requested, now, expires, json.dumps(detail, separators=(',', ':'))),
            )
