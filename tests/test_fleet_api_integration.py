#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from controller.lghs.database import FleetDB

ROOT = Path(__file__).resolve().parents[1]


def load_api():
    path = ROOT / 'controller' / 'lghs-fleet-api'
    loader = importlib.machinery.SourceFileLoader('test_lghs_fleet_api', str(path))
    spec = importlib.util.spec_from_loader('test_lghs_fleet_api', loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class FleetAPIIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.mod = load_api()
        self.mod.DB = FleetDB(root / 'fleet.db')
        self.mod.DB.initialize()
        self.mod.TOKENS = root / 'tokens.json'
        self.mod.CACHE = root / 'cache.json'
        self.mod.LEGACY_COMMANDS = root / 'commands.json'
        self.mod.TOKENS.write_text(json.dumps({
            'version': 2,
            'admin_token': 'admin-secret',
            'devices': {'CS-999': {'token': 'secret'}},
        }))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.mod.Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def request(self, path, method='GET', body=None, token='secret'):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            f'http://127.0.0.1:{self.port}{path}',
            data=data,
            method=method,
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            },
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode())

    def report(self, sequence, command_states=None, sudo_requests=None, current_commit=None):
        current_commit = current_commit or ('a' * 40)
        return self.request('/v1/report/CS-999', 'POST', {
            'protocol': 1,
            'agent_version': '0.6.0-dev',
            'device_id': 'CS-999',
            'boot_id': 'boot-1',
            'sequence': sequence,
            'sent_at': time.time(),
            'payload': {
                'metrics': {'cpu_pct': 7.5, 'disk_pct': 10.0, 'temp_c': 42.0},
                'health': {
                    'reboot_required': False,
                    'inventory': {
                        'hostname': 'CS-999',
                        'role': 'student',
                        'model': 'Raspberry Pi 5 Model B Rev 1.0',
                        'ram_mb': 8192,
                        'serial': '10000000deadbeef',
                        'current_commit': current_commit,
                        'current_version': '0.6.0-dev',
                    },
                },
                'health_report': {
                    'health_version': 1,
                    'checks': [
                        {'id': 'service.lghs-agent', 'state': 'pass', 'severity': 'critical'},
                        {'id': 'hardware.temperature', 'state': 'pass', 'severity': 'warning'},
                    ],
                },
                'command_states': command_states or [],
                'sudo_requests': sudo_requests or [],
                'audit_batches': [],
                'version': '0.6.0-dev',
            },
        })

    def test_health_and_end_to_end_command_state(self):
        status, health = self.request('/health')
        self.assertEqual(status, 200)
        self.assertEqual(health['protocol'], 1)
        self.assertEqual(health['database'], 'sqlite-wal')
        self.assertEqual(health['command_transport'], 'long-poll')
        self.assertEqual(health['fleet_operations'], 1)
        self.assertTrue(health['exact_commit_deployments'])
        self.assertTrue(health['inventory_reporting'])
        self.assertTrue(health['desired_state_reconciliation'])

        cid = self.mod.DB.create_command('CS-999', 'lghs-update', command_id='cmd-http')
        status, first = self.report(1)
        self.assertEqual(status, 202)
        self.assertEqual([row['id'] for row in first['commands']], [cid])
        self.assertEqual(self.mod.DB.get_command(cid)['state'], 'delivered')

        now = time.time()
        self.report(2, [{
            'id': cid,
            'action': 'lghs-update',
            'state': 'accepted',
            'received_at': now - 0.2,
            'accepted_at': now,
            'updated_at': now,
            'stage': 'Accepted',
            'progress': 0,
        }])
        row = self.mod.DB.get_command(cid)
        self.assertEqual(row['state'], 'accepted')
        self.assertIsNotNone(row['received_at'])
        self.assertIsNotNone(row['accepted_at'])

        run_at = time.time()
        self.report(3, [{
            'id': cid,
            'action': 'lghs-update',
            'state': 'running',
            'received_at': now - 0.2,
            'accepted_at': now,
            'running_at': run_at,
            'updated_at': run_at,
            'stage': 'Installing',
            'progress': 50,
        }])
        self.assertEqual(self.mod.DB.get_command(cid)['state'], 'running')

        done_at = time.time()
        self.report(4, [{
            'id': cid,
            'action': 'lghs-update',
            'state': 'succeeded',
            'received_at': now - 0.2,
            'accepted_at': now,
            'running_at': run_at,
            'succeeded_at': done_at,
            'updated_at': done_at,
            'stage': 'Complete',
            'progress': 100,
        }])
        row = self.mod.DB.get_command(cid)
        self.assertEqual(row['state'], 'succeeded')
        self.assertIsNotNone(row['received_at'])
        self.assertIsNotNone(row['accepted_at'])
        self.assertIsNotNone(row['started_at'])
        self.assertIsNotNone(row['completed_at'])

    def test_admin_inventory_groups_and_exact_commit_deployment(self):
        current = 'a' * 40
        target = 'b' * 40
        self.report(1, current_commit=current)

        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.request('/v1/admin/devices', token='secret')
        self.assertEqual(denied.exception.code, 401)

        status, inventory = self.request('/v1/admin/devices', token='admin-secret')
        self.assertEqual(status, 200)
        device = inventory['devices'][0]
        self.assertEqual(device['device_id'], 'CS-999')
        self.assertEqual(device['hostname'], 'CS-999')
        self.assertEqual(device['role'], 'student')
        self.assertEqual(device['model'], 'Raspberry Pi 5 Model B Rev 1.0')
        self.assertEqual(device['ram_mb'], 8192)
        self.assertEqual(device['serial'], '10000000deadbeef')
        self.assertEqual(device['current_commit'], current)
        self.assertEqual(device['current_version'], '0.6.0-dev')
        self.assertEqual(device['health_state'], 'healthy')
        self.assertEqual(device['boot_id'], 'boot-1')
        self.assertIsNotNone(device['last_seen'])
        self.assertEqual(device['sync_state'], 'no_desired_state')

        status, tags = self.request(
            '/v1/admin/devices/CS-999/tags', 'POST',
            {'tags': ['room:cs-lab', 'ring:canary', 'room:cs-lab']}, token='admin-secret',
        )
        self.assertEqual(status, 200)
        self.assertEqual(tags['tags'], ['ring:canary', 'room:cs-lab'])

        status, group = self.request(
            '/v1/admin/groups', 'POST',
            {'group_id': 'canary', 'name': 'Canary', 'description': 'First rollout wave'},
            token='admin-secret',
        )
        self.assertEqual(status, 201)
        self.assertEqual(group['group_id'], 'canary')
        status, member = self.request('/v1/admin/groups/canary/members/CS-999', 'POST', {}, token='admin-secret')
        self.assertEqual(status, 200)
        self.assertEqual(member['device_id'], 'CS-999')

        status, deployment = self.request(
            '/v1/admin/deployments', 'POST',
            {
                'deployment_id': 'dep-http',
                'name': '0.6 canary',
                'device_id': 'CS-999',
                'target_commit': target,
                'target_version': '0.6.0-dev',
                'created_by': 'cs_admin',
                'strategy': {'type': 'single-device'},
            },
            token='admin-secret',
        )
        self.assertEqual(status, 201)
        self.assertEqual(deployment['deployment_id'], 'dep-http')
        self.assertTrue(deployment['dispatch_ready'])
        cid = deployment['command_id']
        command = self.mod.DB.get_command(cid)
        self.assertEqual(json.loads(command['payload_json'])['target_commit'], target)
        self.assertEqual(json.loads(command['payload_json'])['deployment_id'], 'dep-http')
        self.assertEqual(self.mod.DB.get_device('CS-999')['desired_commit'], target)

        status, pending = self.request('/v1/admin/devices/CS-999', token='admin-secret')
        self.assertEqual(status, 200)
        self.assertEqual(pending['device']['sync_state'], 'update_pending')
        self.assertEqual(pending['device']['desired_version'], '0.6.0-dev')

        status, delivered = self.report(2, current_commit=current)
        self.assertEqual([row['id'] for row in delivered['commands']], [cid])
        self.assertEqual(delivered['commands'][0]['payload']['target_commit'], target)
        status, updating = self.request('/v1/admin/devices/CS-999', token='admin-secret')
        self.assertEqual(updating['device']['sync_state'], 'updating')
        self.assertEqual(updating['device']['latest_deployment']['execution_state'], 'delivered')

        accepted_at = time.time()
        self.report(3, [{
            'id': cid, 'action': 'lghs-update', 'state': 'accepted',
            'received_at': accepted_at - .1, 'accepted_at': accepted_at,
            'updated_at': accepted_at, 'stage': 'Accepted by executor', 'progress': 0,
        }], current_commit=current)
        run_at = time.time()
        self.report(4, [{
            'id': cid, 'action': 'lghs-update', 'state': 'running',
            'received_at': accepted_at - .1, 'accepted_at': accepted_at,
            'running_at': run_at, 'updated_at': run_at,
            'stage': 'Installing exact commit', 'progress': 50,
        }], current_commit=current)
        done_at = time.time()
        self.report(5, [{
            'id': cid, 'action': 'lghs-update', 'state': 'succeeded',
            'received_at': accepted_at - .1, 'accepted_at': accepted_at,
            'running_at': run_at, 'succeeded_at': done_at, 'updated_at': done_at,
            'stage': 'Complete', 'progress': 100,
        }], current_commit=current)

        status, detail = self.request('/v1/admin/deployments/dep-http', token='admin-secret')
        self.assertEqual(status, 200)
        self.assertEqual(detail['deployment']['target_commit'], target)
        self.assertEqual(detail['deployment']['state'], 'succeeded')
        self.assertEqual(detail['executions'][0]['previous_commit'], current)
        self.assertEqual(detail['executions'][0]['state'], 'succeeded')
        self.assertEqual(detail['executions'][0]['stage'], 'Complete')

        status, verifying = self.request('/v1/admin/devices/CS-999', token='admin-secret')
        self.assertEqual(verifying['device']['current_commit'], current)
        self.assertEqual(verifying['device']['desired_commit'], target)
        self.assertEqual(verifying['device']['sync_state'], 'verification_pending')

        self.report(6, current_commit=target)
        status, synced = self.request('/v1/admin/devices/CS-999', token='admin-secret')
        self.assertEqual(synced['device']['current_commit'], target)
        self.assertEqual(synced['device']['desired_commit'], target)
        self.assertEqual(synced['device']['sync_state'], 'in_sync')

        with self.assertRaises(urllib.error.HTTPError) as moving:
            self.request(
                '/v1/admin/deployments', 'POST',
                {'name': 'bad', 'device_id': 'CS-999', 'target_commit': 'release-0.6.0-fleet-operations'},
                token='admin-secret',
            )
        self.assertEqual(moving.exception.code, 400)

    def test_sudo_snapshot_reaches_sqlite(self):
        self.report(1, sudo_requests=[{
            'id': 'sudo-1',
            'status': 'pending',
            'command': 'apt install python3-numpy',
            'requester': 'lg_cs_cont',
            'requested_epoch': 100,
            'expires_epoch': time.time() + 60,
        }])
        with self.mod.DB.connect() as db:
            row = db.execute('SELECT state,command FROM sudo_requests WHERE request_id=?', ('sudo-1',)).fetchone()
        self.assertEqual(row['state'], 'pending')
        self.assertEqual(row['command'], 'apt install python3-numpy')


if __name__ == '__main__':
    unittest.main()
