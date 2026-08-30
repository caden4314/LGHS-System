#!/usr/bin/env python3
import tempfile
import time
import unittest
from pathlib import Path

from controller.lghs.database import FleetDB
from controller.lghs.protocol import ProtocolError, TelemetryEnvelope, normalize_command_state, state_can_advance


class ProtocolTests(unittest.TestCase):
    def test_state_normalization(self):
        self.assertEqual(normalize_command_state("pending"), "queued")
        self.assertEqual(normalize_command_state("complete"), "succeeded")
        self.assertTrue(state_can_advance("received", "accepted"))
        self.assertFalse(state_can_advance("running", "accepted"))

    def test_envelope(self):
        now = time.time()
        env = TelemetryEnvelope.from_mapping(
            {
                "protocol": 1,
                "agent_version": "0.5.0",
                "device_id": "cs-999",
                "boot_id": "boot-1",
                "sequence": 7,
                "sent_at": now,
                "payload": {"cpu_pct": 12.3},
            },
            now=now,
        )
        self.assertEqual(env.device_id, "CS-999")
        self.assertEqual(env.sequence, 7)
        with self.assertRaises(ProtocolError):
            TelemetryEnvelope.from_mapping({"protocol": 2}, now=now)


class FleetDBTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "fleet.db"
        self.store = FleetDB(self.db_path)
        self.store.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def test_wal_and_schema(self):
        with self.store.connect() as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            version = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
            self.assertEqual(version, "1")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for required in {
            "devices", "telemetry_latest", "commands", "command_events",
            "warnings", "warning_events", "deployments", "deployment_executions",
            "sudo_requests", "audit_events", "notifications", "settings",
        }:
            self.assertIn(required, tables)

    def test_telemetry_sequence_rejects_regression_same_boot(self):
        self.store.record_telemetry(
            "CS-999", {"cpu_pct": 10}, received_at=100, sent_at=99,
            agent_version="0.5.0", protocol=1, boot_id="boot-a", sequence=10,
        )
        with self.assertRaises(ValueError):
            self.store.record_telemetry(
                "CS-999", {"cpu_pct": 11}, received_at=101, sent_at=100,
                agent_version="0.5.0", protocol=1, boot_id="boot-a", sequence=9,
            )
        # A reboot resets sequence ordering because boot_id changed.
        self.store.record_telemetry(
            "CS-999", {"cpu_pct": 12}, received_at=102, sent_at=101,
            agent_version="0.5.0", protocol=1, boot_id="boot-b", sequence=0,
        )
        latest = self.store.latest_telemetry("CS-999")
        self.assertEqual(latest["boot_id"], "boot-b")
        self.assertEqual(latest["sequence"], 0)

    def test_command_timeline_is_transactional(self):
        cid = self.store.create_command("CS-999", "lghs-update", command_id="cmd-1", now=10)
        self.assertEqual(cid, "cmd-1")
        self.store.transition_command(cid, "delivered", now=11)
        self.store.transition_command(cid, "received", now=12)
        self.store.transition_command(cid, "accepted", now=13)
        self.store.transition_command(cid, "running", stage="Installing", progress=50, now=14)
        row = self.store.transition_command(cid, "succeeded", stage="Complete", progress=100, now=15)
        self.assertEqual(row["state"], "succeeded")
        self.assertEqual(row["accepted_at"], 13)
        self.assertEqual(row["started_at"], 14)
        self.assertEqual(row["completed_at"], 15)
        with self.store.connect() as db:
            states = [r[0] for r in db.execute(
                "SELECT state FROM command_events WHERE command_id=? ORDER BY id", (cid,)
            )]
        self.assertEqual(states, ["queued", "delivered", "received", "accepted", "running", "succeeded"])

    def test_terminal_command_cannot_regress(self):
        cid = self.store.create_command("CS-999", "os-update")
        self.store.transition_command(cid, "failed")
        with self.assertRaises(ValueError):
            self.store.transition_command(cid, "running")


if __name__ == "__main__":
    unittest.main()
