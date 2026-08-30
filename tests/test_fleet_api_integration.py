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
        self.mod.TOKENS.write_text(json.dumps({'devices': {'CS-999': {'token': 'secret'}}}))
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
            headers={
                'Authorization': 'Bearer secret',
                'Content-Type': 'application/json',
            },
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode())

    def report(self, sequence, command_states=None, sudo_requests=None):
        return self.request('/v1/report/CS-999', 'POST', {
            'protocol': 1,
            'agent_version': '0.5.0',
            'device_id': 'CS-999',
            'boot_id': 'boot-1',
            'sequence': sequence,
            'sent_at': time.time(),
            'payload': {
                'metrics': {'cpu_pct': 7.5, 'disk_pct': 10.0, 'temp_c': 42.0},
                'health': {'reboot_required': False},
                'command_states': command_states or [],
                'sudo_requests': sudo_requests or [],
                'audit_batches': [],
            },
        })

    def test_health_and_end_to_end_command_state(self):
        status, health = self.request('/health')
        self.assertEqual(status, 200)
        self.assertEqual(health['protocol'], 1)
        self.assertEqual(health['database'], 'sqlite-wal')
        self.assertEqual(health['command_transport'], 'long-poll')

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
