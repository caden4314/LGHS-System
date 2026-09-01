#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import json
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from controller.lghs.database import FleetDB

ROOT = Path(__file__).resolve().parents[1]


def load_api():
    path = ROOT / 'controller' / 'lghs-fleet-api'
    loader = importlib.machinery.SourceFileLoader('test_lghs_fleet_api_maintenance', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class FleetAPIMaintenanceTests(unittest.TestCase):
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
        for device, boot in (('CS-001', 'boot-a'), ('CS-002', 'boot-b')):
            self.mod.DB.upsert_device(device, boot_id=boot, last_seen=time.time())
            self.mod.DB.update_device_inventory(device, current_commit=self.old, current_version='0.6.0-dev', health_state='healthy')
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

    def request(self, path, method='GET', body=None, token='admin-secret'):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            f'http://127.0.0.1:{self.port}{path}',
            data=data,
            method=method,
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode())

    def test_maintenance_policy_and_device_view(self):
        policy = {
            'timezone': 'UTC',
            'windows': [{'days': ['mon', 'tue', 'wed', 'thu', 'fri'], 'start': '15:30', 'end': '06:30'}],
            'actor': 'cs_admin',
        }
        status, saved = self.request('/v1/admin/maintenance/group/lab', 'POST', policy)
        self.assertEqual(status, 200)
        self.assertEqual(saved['group_id'], 'lab')
        self.assertEqual(saved['policy']['timezone'], 'UTC')

        status, policies = self.request('/v1/admin/maintenance/policies')
        self.assertEqual(status, 200)
        self.assertEqual(len(policies['policies']), 1)
        self.assertEqual(policies['policies'][0]['scope'], 'group')
        self.assertEqual(policies['policies'][0]['id'], 'lab')

        status, effective = self.request('/v1/admin/maintenance/devices/CS-001')
        self.assertEqual(status, 200)
        self.assertTrue(effective['maintenance']['managed'])
        self.assertEqual(effective['maintenance']['policies'][0]['id'], 'lab')

        status, device = self.request('/v1/admin/devices/CS-001')
        self.assertEqual(status, 200)
        self.assertIn('maintenance', device['device'])
        self.assertTrue(device['device']['maintenance']['managed'])

        status, cleared = self.request('/v1/admin/maintenance/group/lab/clear', 'POST', {'actor': 'cs_admin'})
        self.assertEqual(status, 200)
        self.assertTrue(cleared['cleared'])
        _, effective = self.request('/v1/admin/maintenance/devices/CS-001')
        self.assertFalse(effective['maintenance']['managed'])

    def test_reboot_schedule_routes_dispatch_and_cancel(self):
        now = time.time()
        status, created = self.request('/v1/admin/reboots', 'POST', {
            'schedule_id': 'api-reboot',
            'group_id': 'lab',
            'mode': 'at',
            'scheduled_at': now,
            'reason': 'API integration test',
            'created_by': 'cs_admin',
        })
        self.assertEqual(status, 201)
        self.assertEqual(created['schedule_id'], 'api-reboot')
        self.assertEqual(created['resolved_devices'], ['CS-001', 'CS-002'])
        self.assertEqual(created['state'], 'queued')

        status, listed = self.request('/v1/admin/reboots')
        self.assertEqual(status, 200)
        self.assertEqual([row['schedule_id'] for row in listed['reboots']], ['api-reboot'])

        status, detail = self.request('/v1/admin/reboots/api-reboot')
        self.assertEqual(status, 200)
        self.assertEqual(detail['reboot']['executions']['CS-001']['boot_id_before'], 'boot-a')

        status, reconciled = self.request('/v1/admin/reboots/api-reboot/reconcile', 'POST', {})
        self.assertEqual(status, 200)
        self.assertEqual(reconciled['state'], 'running')
        self.assertEqual({row['action'] for row in reconciled['actions']}, {'dispatched'})
        command_ids = [row['command_id'] for row in reconciled['actions']]
        self.assertEqual(len(command_ids), 2)
        self.assertTrue(all(self.mod.DB.get_command(cid)['action'] == 'reboot' for cid in command_ids))

        status, canceled = self.request('/v1/admin/reboots/api-reboot/cancel', 'POST', {'actor': 'cs_admin'})
        self.assertEqual(status, 200)
        self.assertEqual(canceled['state'], 'canceled')
        self.assertEqual(sorted(canceled['canceled_devices']), ['CS-001', 'CS-002'])
        self.assertTrue(all(self.mod.DB.get_command(cid)['state'] == 'canceled' for cid in command_ids))

    def test_health_advertises_maintenance_and_reboots(self):
        status, health = self.request('/health')
        self.assertEqual(status, 200)
        self.assertTrue(health['maintenance_windows'])
        self.assertTrue(health['scheduled_reboots'])
        self.assertTrue(health['typed_reboot_command'])


if __name__ == '__main__':
    unittest.main()
