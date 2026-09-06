#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path

from controller.lghs.database import FleetDB

ROOT = Path(__file__).resolve().parents[1]


def load_script(name, relative):
    path = ROOT / relative
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class ClassroomReadyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self.mod = load_script('test_classroom_ready_tool', 'controller/lghs-classroom-ready')
        self.mod.DB = FleetDB(root / 'fleet.db')
        self.mod.DB.initialize()
        self.mod.REGISTRY = root / 'fleet.json'
        self.mod.CONTROLLER_COMMIT = root / 'current-commit'
        self.commit = 'a' * 40
        self.mod.CONTROLLER_COMMIT.write_text(self.commit + '\n', encoding='utf-8')
        self.mod.REGISTRY.write_text(json.dumps({'version': 1, 'devices': {'CS-08': {
            'transport': 'cloudflare',
            'ssh_host': 'ssh-cs-08.example.invalid',
            'ssh_user': 'cs_admin',
            'provision_order': ['bluetooth', 'cloudflare', 'cloudflare-verified', 'fleet', 'first-telemetry'],
        }}}), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, *, channel='main', failed_units=None, sudo=True):
        checks = []
        for check_id in (
            'service.NetworkManager', 'service.ssh', 'service.lghs-agent',
            'service.lghs-command-executor', 'service.lghs-policy', 'service.lghs-lifecycle',
            'transport.controller', 'release.signing-key',
        ):
            checks.append({'id': check_id, 'state': 'pass', 'severity': 'critical', 'observed': 'active'})
        checks.append({'id': 'sudo.broker', 'state': 'pass' if sudo else 'fail', 'severity': 'critical', 'observed': sudo})
        failed = list(failed_units or [])
        checks.append({'id': 'system.failed-units', 'state': 'fail' if failed else 'pass', 'severity': 'warning', 'observed': failed})
        return {
            'health': {'inventory': {
                'hostname': 'CS-08', 'role': 'student', 'current_commit': self.commit,
                'current_version': '0.6.0', 'update_channel': channel,
            }},
            'health_report': {'health_version': 2, 'checks': checks},
        }

    def report(self, payload=None, now=None):
        ts = time.time() if now is None else float(now)
        self.mod.DB.record_telemetry('CS-08', payload or self.payload(), received_at=ts, sent_at=ts, agent_version='0.6.0', protocol=1, boot_id='boot-8', sequence=1)
        self.mod.DB.update_device_inventory('CS-08', hostname='CS-08', role='student', current_commit=self.commit, current_version='0.6.0', health_state='healthy', now=ts)
        return ts

    def test_ready_requires_all_runtime_evidence(self):
        now = self.report()
        result = self.mod.evaluate('CS-08', now=now + 1)
        self.assertTrue(result['ready'])
        self.assertTrue(all(result['sections'].values()))
        self.assertEqual(result['failed_units'], [])
        self.assertEqual(result['channel'], 'main')
        text = self.mod.render(result)
        self.assertIn('CS-08 CLASSROOM READY', text)
        self.assertIn('Sudo broker', text)
        self.assertIn('Failed units ..... 0', text)

    def test_stale_fleet_or_wrong_version_blocks_ready(self):
        now = self.report()
        stale = self.mod.evaluate('CS-08', now=now + 90, max_age=30)
        self.assertFalse(stale['ready'])
        self.assertFalse(stale['sections']['Fleet'])
        wrong = self.mod.evaluate('CS-08', commit='b' * 40, now=now + 1)
        self.assertFalse(wrong['ready'])
        self.assertFalse(wrong['sections']['Version'])

    def test_policy_sudo_and_failed_units_are_hard_gates(self):
        now = self.report(self.payload(failed_units=['bad.service'], sudo=False))
        result = self.mod.evaluate('CS-08', now=now + 1)
        self.assertFalse(result['ready'])
        self.assertFalse(result['sections']['Sudo broker'])
        self.assertEqual(result['failed_units'], ['bad.service'])

    def legacy_registry(self):
        raw = json.loads(self.mod.REGISTRY.read_text(encoding='utf-8'))
        entry = raw['devices']['CS-08']
        entry.pop('provision_order', None)
        entry.pop('source', None)
        self.mod.REGISTRY.write_text(json.dumps(raw), encoding='utf-8')

    def test_verified_legacy_migration_records_provenance(self):
        self.legacy_registry()
        now = self.report()
        before = self.mod.evaluate('CS-08', now=now + 1)
        self.assertFalse(before['sections']['Bootstrap'])
        migration = load_script('test_migration_tool', 'controller/lghs-verify-migration')
        after = migration.verify_and_record('CS-08', now=now + 1, ready_module=self.mod)
        self.assertTrue(after['ready'])
        raw = json.loads(self.mod.REGISTRY.read_text(encoding='utf-8'))
        entry = raw['devices']['CS-08']
        self.assertEqual(entry['source'], 'managed-migration-verified')
        self.assertEqual(entry['migration_verifier'], 'lghs-verify-migration-v1')
        self.assertEqual(entry['provision_order'][:3], ['managed-migration', 'cloudflare', 'cloudflare-verified'])

    def test_verified_legacy_migration_refuses_failed_runtime_gate(self):
        self.legacy_registry()
        now = self.report(self.payload(sudo=False))
        migration = load_script('test_migration_refusal', 'controller/lghs-verify-migration')
        with self.assertRaisesRegex(ValueError, 'Sudo broker'):
            migration.verify_and_record('CS-08', now=now + 1, ready_module=self.mod)


if __name__ == '__main__':
    unittest.main()
