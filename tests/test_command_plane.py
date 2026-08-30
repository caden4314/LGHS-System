#!/usr/bin/env python3
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_script(name, relative):
    path = ROOT / relative
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class CommandPlaneTests(unittest.TestCase):
    def test_received_command_is_duplicate_suppressed(self):
        mod = load_script("test_fleet_command", "controller/lghs-fleet-command")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.COMMANDS = root / "commands.json"
            mod.COMMAND_LOCK = root / "commands.lock"
            mod.REGISTRY = root / "fleet.json"
            mod.REGISTRY.write_text(json.dumps({"devices": {"CS-999": {}}}))
            mod.COMMANDS.write_text(json.dumps({
                "version": 2,
                "devices": {"CS-999": [{
                    "id": "existing-id",
                    "action": "lghs-update",
                    "state": "received",
                    "created_at": time.time(),
                }]},
            }))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                mod.enqueue("CS-999", "lghs-update")
            data = json.loads(mod.COMMANDS.read_text())
            self.assertEqual(out.getvalue().strip(), "existing-id")
            self.assertEqual(len(data["devices"]["CS-999"]), 1)

    def test_api_redelivers_received_until_accepted(self):
        mod = load_script("test_fleet_api_redelivery", "controller/lghs-fleet-api")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.COMMANDS = root / "commands.json"
            mod.COMMAND_LOCK_FILE = root / "commands.lock"
            mod.COMMANDS.write_text(json.dumps({
                "version": 2,
                "devices": {"CS-999": [{
                    "id": "cmd-1",
                    "action": "lghs-update",
                    "state": "received",
                    "created_at": time.time(),
                }]},
            }))
            with mod.command_file_lock():
                delivered = mod.commands_for("CS-999")
            self.assertEqual([x["id"] for x in delivered], ["cmd-1"])
            row = json.loads(mod.COMMANDS.read_text())["devices"]["CS-999"][0]
            self.assertEqual(row["state"], "received")
            self.assertGreaterEqual(row["deliveries"], 1)

    def test_expired_command_becomes_timed_out_instead_of_disappearing(self):
        mod = load_script("test_fleet_api_timeout", "controller/lghs-fleet-api")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.COMMANDS = root / "commands.json"
            mod.COMMAND_LOCK_FILE = root / "commands.lock"
            mod.COMMAND_TTL = 10
            mod.COMMANDS.write_text(json.dumps({
                "version": 2,
                "devices": {"CS-999": [{
                    "id": "cmd-old",
                    "action": "os-update",
                    "state": "delivered",
                    "created_at": time.time() - 60,
                }]},
            }))
            with mod.command_file_lock():
                delivered = mod.commands_for("CS-999")
            self.assertEqual(delivered, [])
            rows = json.loads(mod.COMMANDS.read_text())["devices"]["CS-999"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["state"], "timed_out")
            self.assertIn("timed_out_at", rows[0])

    def test_student_retries_received_command_after_restart_gap(self):
        mod = load_script("test_telemetry_retry", "student/lghs-telemetry-push")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.COMMAND_STATE = root / "telemetry" / "command-state.json"
            mod.LEGACY_COMMAND_STATE = root / "legacy-command-state.json"
            mod.COMMAND_STATE.parent.mkdir(parents=True)
            mod.COMMAND_STATE.write_text(json.dumps({
                "commands": [{
                    "id": "cmd-2",
                    "action": "lghs-update",
                    "state": "received",
                    "received_at": time.time() - 5,
                }]
            }))
            mod.run = lambda args: subprocess.CompletedProcess(args, 0, "job-id\n", "")
            mod.accept_commands([{"id": "cmd-2", "action": "lghs-update"}])
            row = json.loads(mod.COMMAND_STATE.read_text())["commands"][0]
            self.assertEqual(row["state"], "accepted")
            self.assertIn("accepted_at", row)


if __name__ == "__main__":
    unittest.main()
