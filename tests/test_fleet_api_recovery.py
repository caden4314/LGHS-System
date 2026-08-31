#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from controller.lghs.database import FleetDB

ROOT = Path(__file__).resolve().parents[1]


def load_api():
    path = ROOT / 'controller' / 'lghs-fleet-api'
    loader = importlib.machinery.SourceFileLoader('test_lghs_fleet_api_recovery', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class FleetAPIRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.mod = load_api()
        self.mod.DB = FleetDB(root / 'fleet.db')
        self.mod.DB.initialize()
        self.mod.TOKENS = root / 'tokens.json'
        self.mod.CACHE = root / 'cache.json'
        self.mod.LEGACY_COMMANDS = root / 'commands.json'
        self.mod.TOKENS.write_text(json.dumps({'version': 2, 'admin_token': 'admin-secret', 'devices': {}}))
        self.old = 'a' * 40
        self.target = 'b' * 40
        for device in ('CS-001', 'CS-002'):
            self.mod.DB.update_device_inventory(device, current_commit=self.old, current_version='0.5.1', health_state='healthy')
        self.mod.DB.create_group('Lab', group_id='lab')
        for device in ('CS-001', 'CS-002'):
            self.mod.DB.add_device_to_group(device, 'lab')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.mod.Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def request(self, path, method='GET', body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            f'http://127.0.0.1:{self.port}{path}',
            data=data,
            method=method,
            headers={'Authorization': 'Bearer admin-secret', 'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode())

    def test_group_target_is_frozen_and_recovery_routes_work(self):
        status, created = self.request('/v1/admin/deployments', 'POST', {
            'deployment_id': 'dep-api-recovery',
            'name': 'API recovery rollout',
            'group_id': 'lab',
            'target_commit': self.target,
            'strategy': {'type': 'phased', 'canary_count': 1, 'wave_percentages': [100], 'soak_seconds': 0},
            'policy': {'auto_advance': False},
            'dispatch': False,
        })
        self.assertEqual(status, 201)
        self.assertEqual(created['target']['resolved_devices'], ['CS-001', 'CS-002'])
        self.assertNotIn('command_ids', created)

        self.mod.DB.update_device_inventory('CS-003', current_commit=self.old, current_version='0.5.1', health_state='healthy')
        self.mod.DB.add_device_to_group('CS-003', 'lab')
        _, detail = self.request('/v1/admin/deployments/dep-api-recovery')
        self.assertEqual(detail['deployment']['target']['resolved_devices'], ['CS-001', 'CS-002'])

        _, dispatched = self.request('/v1/admin/deployments/dep-api-recovery/dispatch', 'POST', {'phase': 0})
        self.assertEqual(len(dispatched['command_ids']), 1)
        old_cid = dispatched['command_ids'][0]
        canary = next(x for x in self.mod.DB.list_deployment_executions('dep-api-recovery') if x['phase'] == 0)
        self.mod.DB.transition_command(old_cid, 'failed', stage='Install failed', message='simulated')
        with self.mod.DB.transaction() as db:
            db.execute("UPDATE deployment_executions SET state='failed',stage='Install failed',error_code='FAILED' WHERE deployment_id=? AND device_id=?", ('dep-api-recovery', canary['device_id']))
            db.execute("UPDATE deployments SET state='paused',paused_reason='canary failure' WHERE deployment_id=?", ('dep-api-recovery',))

        _, retried = self.request('/v1/admin/deployments/dep-api-recovery/retry-failed', 'POST', {'actor': 'cs_admin'})
        self.assertEqual(retried['devices'], [canary['device_id']])
        self.assertEqual(len(retried['command_ids']), 1)
        self.assertNotEqual(retried['command_ids'][0], old_cid)
        self.assertEqual(self.mod.DB.get_deployment('dep-api-recovery')['state'], 'running')

        _, canceled = self.request('/v1/admin/deployments/dep-api-recovery/cancel-remaining', 'POST', {'actor': 'cs_admin'})
        self.assertEqual(canceled['action'], 'canceled')
        self.assertEqual(self.mod.DB.get_deployment('dep-api-recovery')['state'], 'canceled')

        self.mod.DB.update_device_inventory(canary['device_id'], current_commit=self.target, health_state='healthy')
        _, rollback = self.request('/v1/admin/deployments/dep-api-recovery/rollback', 'POST', {'actor': 'cs_admin', 'dispatch': False})
        self.assertEqual(rollback['action'], 'rollback-created')
        self.assertEqual(len(rollback['rollbacks']), 1)
        rollback_id = rollback['rollbacks'][0]['deployment_id']
        self.assertEqual(self.mod.DB.get_deployment(rollback_id)['target_commit'], self.old)

    def test_cancelled_deployment_is_not_resurrected_by_late_sync(self):
        _, created = self.request('/v1/admin/deployments', 'POST', {
            'deployment_id': 'dep-cancel-lock',
            'name': 'Cancel lock',
            'device_id': 'CS-001',
            'target_commit': self.target,
            'strategy': {'type': 'all-at-once'},
            'dispatch': True,
        })
        cid = created['command_ids'][0]
        self.mod.DB.transition_command(cid, 'delivered')
        _, canceled = self.request('/v1/admin/deployments/dep-cancel-lock/cancel-remaining', 'POST', {'actor': 'cs_admin'})
        self.assertEqual(canceled['action'], 'canceled')
        self.mod.sync_deployment_execution(cid)
        self.assertEqual(self.mod.DB.get_deployment('dep-cancel-lock')['state'], 'canceled')


if __name__ == '__main__':
    unittest.main()
