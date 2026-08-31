#!/usr/bin/env python3
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import subprocess
import sys
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
    def test_received_command_is_duplicate_suppressed_for_same_payload(self):
        mod = load_script('test_fleet_command', 'controller/lghs-fleet-command')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.DB = FleetDB(root / 'fleet.db')
            mod.REGISTRY = root / 'fleet.json'
            mod.REGISTRY.write_text(json.dumps({'devices': {'CS-999': {}}}))
            mod.DB.initialize()
            payload = {'target_commit': 'a' * 40}
            existing = mod.DB.create_command('CS-999', 'lghs-update', payload=payload, command_id='existing-id', now=time.time(), dedupe=False)
            mod.DB.transition_command(existing, 'delivered')
            mod.DB.transition_command(existing, 'received')
            mod.DB.export_legacy_commands = lambda *args, **kwargs: None
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                mod.enqueue('CS-999', 'lghs-update', payload)
            self.assertEqual(out.getvalue().strip(), 'existing-id')
            self.assertEqual(len(mod.DB.list_commands('CS-999')), 1)

    def test_same_action_with_different_payload_is_not_deduped(self):
        mod = load_script('test_fleet_command_payload', 'controller/lghs-fleet-command')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mod.DB = FleetDB(root / 'fleet.db')
            mod.REGISTRY = root / 'fleet.json'
            mod.REGISTRY.write_text(json.dumps({'devices': {'CS-999': {}}}))
            mod.DB.initialize()
            mod.DB.export_legacy_commands = lambda *args, **kwargs: None
            with contextlib.redirect_stdout(io.StringIO()):
                mod.enqueue('CS-999', 'lghs-update', {'target_commit': 'a' * 40})
                mod.enqueue('CS-999', 'lghs-update', {'target_commit': 'b' * 40})
            rows = mod.DB.list_commands('CS-999')
            self.assertEqual(len(rows), 2)
            payloads = {json.loads(row['payload_json'])['target_commit'] for row in rows}
            self.assertEqual(payloads, {'a' * 40, 'b' * 40})

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
        self.assertEqual(
            executor.action_command('lghs-update', {'target_commit': target}, 'command-123'),
            [executor.NETQUEUE, 'enqueue', 'local-update', '--commit', target, '--idempotency-key', 'command-123'],
        )
        self.assertEqual(
            executor.action_command('os-update', {}, 'command-os'),
            [executor.NETQUEUE, 'enqueue', 'os-update', '--idempotency-key', 'command-os'],
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

    def configure_queue_temp(self, queue, root):
        queue.QUEUE_DIR = root / 'netqueue'
        queue.JOBS_DIR = queue.QUEUE_DIR / 'jobs'
        queue.IDEMPOTENCY_FILE = queue.QUEUE_DIR / 'idempotency.json'
        queue.LOG = root / 'lghs-netqueue.log'
        queue.start_drain = lambda: None

    def test_idempotent_queue_reuses_same_job_and_rejects_payload_conflict(self):
        queue = load_script('test_netqueue_idempotency', 'updater/lghs-netqueue')
        with tempfile.TemporaryDirectory() as td:
            self.configure_queue_temp(queue, Path(td))
            with contextlib.redirect_stdout(io.StringIO()):
                first = queue.enqueue('local-update', {'target_commit': 'a' * 40}, 'cmd-1')
                second = queue.enqueue('local-update', {'target_commit': 'a' * 40}, 'cmd-1')
            self.assertEqual(first, second)
            self.assertEqual(len(queue.load_jobs()), 1)
            with self.assertRaises(ValueError):
                queue.enqueue('local-update', {'target_commit': 'b' * 40}, 'cmd-1')

    def test_uncertain_idempotent_execution_requires_explicit_retry(self):
        queue = load_script('test_netqueue_uncertain', 'updater/lghs-netqueue')
        with tempfile.TemporaryDirectory() as td:
            self.configure_queue_temp(queue, Path(td))
            with contextlib.redirect_stdout(io.StringIO()):
                queue.enqueue('local-update', {'target_commit': 'a' * 40}, 'cmd-uncertain')
            job = queue.load_jobs()[0]
            self.assertTrue(queue.ledger_before_run(job))
            # Simulate process/controller death after execution began but before
            # the outcome was durably recorded.
            reloaded = queue.load_jobs()[0]
            self.assertFalse(queue.ledger_before_run(reloaded))
            self.assertEqual(queue.load_ledger()['entries']['cmd-uncertain']['state'], 'uncertain')
            with contextlib.redirect_stdout(io.StringIO()):
                queue.retry_idempotent('cmd-uncertain')
            self.assertEqual(queue.load_ledger()['entries']['cmd-uncertain']['state'], 'pending')

    def test_idempotent_timeout_is_held_uncertain(self):
        queue = load_script('test_netqueue_timeout', 'updater/lghs-netqueue')
        with tempfile.TemporaryDirectory() as td:
            self.configure_queue_temp(queue, Path(td))
            with contextlib.redirect_stdout(io.StringIO()):
                queue.enqueue('local-update', {'target_commit': 'a' * 40}, 'cmd-timeout')
            job = queue.load_jobs()[0]
            self.assertTrue(queue.ledger_before_run(job))
            queue.ledger_after_run(job, 124, 'timed out')
            self.assertEqual(queue.load_ledger()['entries']['cmd-timeout']['state'], 'uncertain')

    def test_netqueue_cli_parses_commit_and_idempotency_options(self):
        queue = load_script('test_netqueue_cli', 'updater/lghs-netqueue')
        target = 'a' * 40
        captured = {}

        def fake_enqueue(kind, params, key=None):
            captured.update(kind=kind, params=params, key=key)
            return 'job'

        argv = ['lghs-netqueue', 'enqueue', 'local-update', '--commit', target, '--idempotency-key', 'cmd-55']
        with mock.patch.object(queue, 'require_root', lambda: None), mock.patch.object(queue, 'enqueue', side_effect=fake_enqueue), mock.patch.object(sys, 'argv', argv):
            self.assertEqual(queue.main(), 0)
        self.assertEqual(captured, {'kind': 'local-update', 'params': {'target_commit': target}, 'key': 'cmd-55'})

    def test_executor_inventory_is_safe_on_non_pi_hosts(self):
        executor = load_script('test_command_executor_inventory', 'student/lghs-command-executor')
        inventory = executor.pi_inventory()
        self.assertTrue(inventory['hostname'])
        self.assertIsInstance(inventory.get('ram_mb'), int)
        if inventory.get('current_commit'):
            self.assertRegex(inventory['current_commit'], r'^[0-9a-f]{40}$')
        health = executor.pi_health()
        self.assertEqual(health['inventory']['hostname'], inventory['hostname'])

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
