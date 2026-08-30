"""Transactional SQLite state store for LGHS 0.5.

This module is intentionally usable before every legacy JSON path is removed.
The first migration stages can dual-read/dual-write while this schema becomes
the controller source of truth.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from .protocol import ALLOWED_COMMANDS, normalize_command_state, normalize_device_id, state_can_advance

DEFAULT_DB = Path("/var/lib/lghs/fleet.db")
SCHEMA_VERSION = 1

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    agent_version TEXT,
    protocol INTEGER,
    boot_id TEXT,
    last_sequence INTEGER,
    last_seen REAL,
    transport TEXT,
    ssh_host TEXT,
    labels_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS telemetry_latest (
    device_id TEXT PRIMARY KEY REFERENCES devices(device_id) ON DELETE CASCADE,
    received_at REAL NOT NULL,
    sent_at REAL,
    boot_id TEXT,
    sequence INTEGER,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commands (
    command_id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    state TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    progress REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    deadline_at REAL,
    accepted_at REAL,
    started_at REAL,
    completed_at REAL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_commands_device_created ON commands(device_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_commands_state ON commands(state, updated_at);

CREATE TABLE IF NOT EXISTS command_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id TEXT NOT NULL REFERENCES commands(command_id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    progress REAL,
    created_at REAL NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_command_events_command ON command_events(command_id, id);

CREATE TABLE IF NOT EXISTS warnings (
    warning_id TEXT PRIMARY KEY,
    device_id TEXT REFERENCES devices(device_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    state TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    recommended_action TEXT NOT NULL DEFAULT '',
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    acknowledged_at REAL,
    resolved_at REAL
);
CREATE INDEX IF NOT EXISTS idx_warnings_device_state ON warnings(device_id, state, severity);

CREATE TABLE IF NOT EXISTS warning_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    warning_id TEXT NOT NULL REFERENCES warnings(warning_id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS deployments (
    deployment_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    target_version TEXT,
    target_commit TEXT,
    state TEXT NOT NULL,
    created_by TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    policy_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS deployment_executions (
    deployment_id TEXT NOT NULL REFERENCES deployments(deployment_id) ON DELETE CASCADE,
    device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    command_id TEXT REFERENCES commands(command_id) ON DELETE SET NULL,
    phase INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (deployment_id, device_id)
);

CREATE TABLE IF NOT EXISTS sudo_requests (
    request_id TEXT PRIMARY KEY,
    device_id TEXT REFERENCES devices(device_id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    command TEXT NOT NULL,
    requested_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    expires_at REAL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT REFERENCES devices(device_id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    created_at REAL NOT NULL,
    sequence INTEGER,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_events_device_time ON audit_events(device_id, created_at DESC);

CREATE TABLE IF NOT EXISTS notifications (
    notification_id TEXT PRIMARY KEY,
    device_id TEXT REFERENCES devices(device_id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    state TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class FleetDB:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.execute(
                "INSERT INTO metadata(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield db
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def upsert_device(
        self,
        device_id: str,
        *,
        agent_version: str | None = None,
        protocol: int | None = None,
        boot_id: str | None = None,
        sequence: int | None = None,
        last_seen: float | None = None,
        transport: str | None = None,
        ssh_host: str | None = None,
        labels: Mapping[str, Any] | None = None,
        db: sqlite3.Connection | None = None,
    ) -> str:
        device = normalize_device_id(device_id)
        now = time.time()
        values = (
            device,
            now,
            now,
            agent_version,
            protocol,
            boot_id,
            sequence,
            last_seen,
            transport,
            ssh_host,
            _json(dict(labels or {})),
        )
        sql = """
        INSERT INTO devices(
            device_id,created_at,updated_at,agent_version,protocol,boot_id,
            last_sequence,last_seen,transport,ssh_host,labels_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(device_id) DO UPDATE SET
            updated_at=excluded.updated_at,
            agent_version=COALESCE(excluded.agent_version,devices.agent_version),
            protocol=COALESCE(excluded.protocol,devices.protocol),
            boot_id=COALESCE(excluded.boot_id,devices.boot_id),
            last_sequence=COALESCE(excluded.last_sequence,devices.last_sequence),
            last_seen=COALESCE(excluded.last_seen,devices.last_seen),
            transport=COALESCE(excluded.transport,devices.transport),
            ssh_host=COALESCE(excluded.ssh_host,devices.ssh_host),
            labels_json=CASE WHEN excluded.labels_json='{}' THEN devices.labels_json ELSE excluded.labels_json END
        """
        if db is not None:
            db.execute(sql, values)
        else:
            with self.transaction() as tx:
                tx.execute(sql, values)
        return device

    def record_telemetry(
        self,
        device_id: str,
        payload: Mapping[str, Any],
        *,
        received_at: float | None = None,
        sent_at: float | None = None,
        agent_version: str | None = None,
        protocol: int | None = None,
        boot_id: str | None = None,
        sequence: int | None = None,
    ) -> None:
        device = normalize_device_id(device_id)
        received = time.time() if received_at is None else float(received_at)
        with self.transaction() as db:
            existing = db.execute(
                "SELECT boot_id,last_sequence FROM devices WHERE device_id=?", (device,)
            ).fetchone()
            if existing and boot_id and existing["boot_id"] == boot_id and sequence is not None:
                previous = existing["last_sequence"]
                if previous is not None and int(sequence) < int(previous):
                    raise ValueError("out-of-order telemetry sequence")
            self.upsert_device(
                device,
                agent_version=agent_version,
                protocol=protocol,
                boot_id=boot_id,
                sequence=sequence,
                last_seen=received,
                db=db,
            )
            db.execute(
                """
                INSERT INTO telemetry_latest(device_id,received_at,sent_at,boot_id,sequence,payload_json)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(device_id) DO UPDATE SET
                    received_at=excluded.received_at,
                    sent_at=excluded.sent_at,
                    boot_id=excluded.boot_id,
                    sequence=excluded.sequence,
                    payload_json=excluded.payload_json
                """,
                (device, received, sent_at, boot_id, sequence, _json(dict(payload))),
            )

    def create_command(
        self,
        device_id: str,
        action: str,
        *,
        payload: Mapping[str, Any] | None = None,
        deadline_at: float | None = None,
        command_id: str | None = None,
        now: float | None = None,
    ) -> str:
        device = normalize_device_id(device_id)
        if action not in ALLOWED_COMMANDS:
            raise ValueError(f"unsupported command: {action}")
        ts = time.time() if now is None else float(now)
        cid = command_id or uuid.uuid4().hex
        with self.transaction() as db:
            self.upsert_device(device, db=db)
            db.execute(
                """
                INSERT INTO commands(
                    command_id,device_id,action,state,stage,message,progress,
                    created_at,updated_at,deadline_at,payload_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (cid, device, action, "queued", "Waiting for device", "Queued on controller", 0, ts, ts, deadline_at, _json(dict(payload or {}))),
            )
            db.execute(
                "INSERT INTO command_events(command_id,state,stage,message,progress,created_at) VALUES(?,?,?,?,?,?)",
                (cid, "queued", "Waiting for device", "Queued on controller", 0, ts),
            )
        return cid

    def transition_command(
        self,
        command_id: str,
        state: str,
        *,
        stage: str | None = None,
        message: str | None = None,
        progress: float | None = None,
        now: float | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        new_state = normalize_command_state(state)
        ts = time.time() if now is None else float(now)
        with self.transaction() as db:
            row = db.execute("SELECT * FROM commands WHERE command_id=?", (command_id,)).fetchone()
            if row is None:
                raise KeyError(command_id)
            if not state_can_advance(row["state"], new_state):
                raise ValueError(f"command state regression: {row['state']} -> {new_state}")
            accepted_at = row["accepted_at"]
            started_at = row["started_at"]
            completed_at = row["completed_at"]
            if new_state == "accepted" and accepted_at is None:
                accepted_at = ts
            if new_state == "running" and started_at is None:
                started_at = ts
            if new_state in {"succeeded", "failed", "timed_out", "rejected", "canceled"} and completed_at is None:
                completed_at = ts
            next_stage = row["stage"] if stage is None else stage
            next_message = row["message"] if message is None else message
            next_progress = row["progress"] if progress is None else progress
            db.execute(
                """
                UPDATE commands SET state=?,stage=?,message=?,progress=?,updated_at=?,
                    accepted_at=?,started_at=?,completed_at=? WHERE command_id=?
                """,
                (new_state, next_stage, next_message, next_progress, ts, accepted_at, started_at, completed_at, command_id),
            )
            db.execute(
                """
                INSERT INTO command_events(command_id,state,stage,message,progress,created_at,detail_json)
                VALUES(?,?,?,?,?,?,?)
                """,
                (command_id, new_state, next_stage, next_message, next_progress, ts, _json(dict(detail or {}))),
            )
            updated = db.execute("SELECT * FROM commands WHERE command_id=?", (command_id,)).fetchone()
            return dict(updated)

    def get_command(self, command_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM commands WHERE command_id=?", (command_id,)).fetchone()
            return dict(row) if row else None

    def list_commands(self, device_id: str | None = None, *, limit: int = 64) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self.connect() as db:
            if device_id is None:
                rows = db.execute("SELECT * FROM commands ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            else:
                device = normalize_device_id(device_id)
                rows = db.execute(
                    "SELECT * FROM commands WHERE device_id=? ORDER BY created_at DESC LIMIT ?",
                    (device, limit),
                ).fetchall()
            return [dict(row) for row in rows]

    def latest_telemetry(self, device_id: str) -> dict[str, Any] | None:
        device = normalize_device_id(device_id)
        with self.connect() as db:
            row = db.execute("SELECT * FROM telemetry_latest WHERE device_id=?", (device,)).fetchone()
            if not row:
                return None
            out = dict(row)
            out["payload"] = json.loads(out.pop("payload_json"))
            return out
