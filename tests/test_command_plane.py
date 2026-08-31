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
from unittest import mock

from controller.lghs.database import FleetDB

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
        mod = load_script('test_fleet_command', 'controller/lghs-fleet-command')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.DB = FleetDB(root / 'fleet.db')
            mod.REGISTRY = root / 'fleet.json'
            mod.REGISTRY.write_text(json.dumps({'devices': {'CS-999': {}}}))
            mod.DB.initialize()
            existing = mod.DB.create_command('CS-999', 'lghs-update', command_id='existing-id', now=time.time())
            mod.DB.transition_command(existing, 'delivered')
            mod.DB.transition_command(existing, 'received')
            mod.DB.export_legacy_commands = lambda *args, **kwargs: None
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                mod.enqueue('CS-999', 'lghs-update')
            self.assertEqual(out.getvalue().strip(), 'existing-id')
            self.assertEqual(len(mod.DB.list_commands('CS-999')), 1)

    def test_sqlite_redelivers_received_until_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            store = FleetDB(Path(td) / 'fleet.db')
            store.initialize()
            cid = store.create_command('CS-999', 'lghs-update', command_id='cmd-1')
            first = store.commands_for_delivery('CS-999', min_redelivery=0)
            self.assertEqual([row['id'] for row in first], [cid])
            store.transition_command(cid, 'received')
            second = store.commands_for_delivery('CS-999', min_redelivery=0)
            self.assertEqual([row['id'] for row in second], [cid])
            store.transition_command(cid, 'accepted')
            self.assertEqual(store.commands_for_delivery('CS-999', min_redelivery=0), [])

    def test_expired_command_becomes_timed_out_instead_of_disappearing(self):
        with tempfile.TemporaryDirectory() as td:
            store = FleetDB(Path(td) / 'fleet.db')
            store.initialize()
            cid = store.create_command(
                'CS-999', 'os-update', command_id='cmd-old', now=time.time() - 60,
                deadline_at=time.time() - 1,
            )
            store.commands_for_delivery('CS-999', min_redelivery=0)
            row = store.get_command(cid)
            self.assertIsNotNone(row)
            self.assertEqual(row['state'], 'timed_out')
            self.assertIsNotNone(row['completed_at'])

    def test_exact_commit_payload_is_typed_through_executor_and_queue(self):
        target = 'a' * 40
        executor = load_script('test_command_executor_pinned', 'student/lghs-command-executor')
        self.assertEqual(
            executor.action_command('lghs-update', {'target_commit': target}),
            [executor.NETQUEUE, 'enqueue', 'local-update', '--commit', target],
        )
        with self.assertRaises(ValueError):
            executor.action_command('lghs-update', {'target_commit': 'release-0.6.0-fleet-operations'})

        queue = load_script('test_netqueue_pinned', 'updater/lghs-netqueue')
        job = {'kind': 'local-update', 'params': {'target_commit': target}}
        captured = {}

        def fake_run(cmd, **kwargs):
            captured['cmd'] = cmd
            captured['env'] = kwargs.get('env', {})
            return subprocess.CompletedProcess(cmd, 0, 'ok', '')

        with mock.patch.object(queue.subprocess, 'run', side_effect=fake_run):
            rc, _ = queue.run_job(job)
        self.assertEqual(rc, 0)
        self.assertEqual(captured['cmd'], ['/usr/local/sbin/lghs-update'])
        self.assertEqual(captured['env']['LGHS_TARGET_COMMIT'], target)
        with self.assertRaises(ValueError):
            queue.command_for({'kind': 'local-update', 'params': {'target_commit': 'main'}})

        updater = (ROOT / 'updater' / 'lghs-update').read_text(encoding='utf-8')
        self.assertIn('LGHS_TARGET_COMMIT must be an exact 40-character Git SHA', updater)
        self.assertIn('enqueue local-update --commit "$REQUESTED_TARGET_COMMIT"', updater)
        self.assertIn('git cat-file -e "${REQUESTED_TARGET_COMMIT}^{commit}"', updater)

    def test_student_retries_received_command_after_restart_gap(self):
        mod = load_script('test_telemetry_retry', 'student/lghs-telemetry-push')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.COMMAND_STATE = root / 'telemetry' / 'command-state.json'
            mod.LEGACY_COMMAND_STATE = root / 'legacy-command-state.json'
            mod.COMMAND_STATE.parent.mkdir(parents=True)
            mod.COMMAND_STATE.write_text(json.dumps({
                'commands': [{
                    'id': 'cmd-2',
                    'action': 'lghs-update',
                    'state': 'received',
                    'received_at': time.time() - 5,
                }]
            }))
            mod.run = lambda args: subprocess.CompletedProcess(args, 0, 'job-id\n', '')
            mod.accept_commands([{'id': 'cmd-2', 'action': 'lghs-update'}])
            row = json.loads(mod.COMMAND_STATE.read_text())['commands'][0]
            self.assertEqual(row['state'], 'accepted')
            self.assertIn('accepted_at', row)


if __name__ == '__main__':
    unittest.main()