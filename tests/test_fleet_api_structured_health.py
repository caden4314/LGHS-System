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
from controller.lghs.health import DEFAULT_REQUIRED_CHECKS

ROOT = Path(__file__).resolve().parents[1]


def load_api():
    path = ROOT / 'controller' / 'lghs-fleet-api'
    loader = importlib.machinery.SourceFileLoader('test_lghs_fleet_api_structured_health', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def report_with_root_readonly():
    checks = []
    for check_id in DEFAULT_REQUIRED_CHECKS:
        checks.append({
            'id': check_id,
            'state': 'fail' if check_id == 'storage.root-writable' else 'pass',
            'severity': 'critical' if check_id == 'storage.root-writable' else 'warning',
            'observed': True if check_id == 'storage.root-writable' else 'ok',
            'expected': False if check_id == 'storage.root-writable' else 'pass',
            'remediation': 'inspect:filesystem' if check_id == 'storage.root-writable' else '',
        })
    return {'health_version': 2, 'checks': checks}


class FleetAPIStructuredHealthTests(unittest.TestCase):
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
        self.mod.DB.update_device_inventory('CS-001', current_commit=self.old, current_version='0.5.1', health_state='healthy')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.mod.Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def request(self, path, method='GET', body=None, admin=True):
        data = None if body is None else json.dumps(body).encode()
        headers = {'Content-Type': 'application/json'}
        if admin:
            headers['Authorization'] = 'Bearer admin-secret'
        req = urllib.request.Request(
            f'http://127.0.0.1:{self.port}{path}',
            data=data,
            method=method,
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode())

    def test_health_endpoint_advertises_structured_gate_v2(self):
        status, health = self.request('/health', admin=False)
        self.assertEqual(status, 200)
        self.assertEqual(health['health_schema'], 2)
        self.assertTrue(health['structured_health_gates'])
        self.assertTrue(health['deployment_wave_audit'])

    def test_deployment_detail_returns_exact_blocking_checks(self):
        _, created = self.request('/v1/admin/deployments', 'POST', {
            'deployment_id': 'dep-structured-health',
            'name': 'Structured health API test',
            'device_id': 'CS-001',
            'target_commit': self.target,
            'strategy': {
                'type': 'all-at-once',
                'health_gate': {'max_report_age_seconds': 45},
            },
            'dispatch': True,
        })
        command_id = created['command_ids'][0]
        for state in ('received', 'accepted', 'running', 'succeeded'):
            self.mod.DB.transition_command(command_id, state)
        self.mod.sync_deployment_execution(command_id)
        self.mod.DB.update_device_inventory('CS-001', current_commit=self.target, current_version='0.6.0-dev', health_state='critical')
        now = time.time()
        self.mod.DB.record_telemetry(
            'CS-001',
            {'health_report': report_with_root_readonly(), 'health': {}, 'metrics': {}},
            received_at=now,
            sent_at=now,
            agent_version='0.6.0-dev',
            protocol=1,
            boot_id='boot-api-health',
            sequence=1,
        )

        status, detail = self.request('/v1/admin/deployments/dep-structured-health')
        self.assertEqual(status, 200)
        gate = detail['rollout']['phases'][0]
        self.assertEqual(gate['state'], 'waiting')
        self.assertEqual(gate['health_blocked'], ['CS-001'])
        health = gate['health_details']['CS-001']
        self.assertEqual(health['mode'], 'structured-v2')
        self.assertFalse(health['allowed'])
        blocked = {item['id']: item for item in health['blocked_checks']}
        self.assertIn('storage.root-writable', blocked)
        self.assertEqual(blocked['storage.root-writable']['remediation'], 'inspect:filesystem')
        self.assertIn('storage.root-writable', gate['reason'])


if __name__ == '__main__':
    unittest.main()
