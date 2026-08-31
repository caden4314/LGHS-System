import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path

from controller.lghs.database import FleetDB
from controller.lghs.health import DEFAULT_REQUIRED_CHECKS, device_health_gate
from controller.lghs.rollout import dispatch_phase, freeze_deployment, phase_gate
from controller.lghs.rollout_manager import reconcile_deployment

ROOT = Path(__file__).resolve().parents[1]


def load_agent():
    path = ROOT / 'student' / 'lghs-agent'
    loader = importlib.machinery.SourceFileLoader('structured_health_test_agent', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def pass_report():
    return {
        'health_version': 2,
        'checks': [
            {
                'id': check_id,
                'state': 'pass',
                'severity': 'critical' if check_id in {
                    'service.NetworkManager', 'service.lghs-policy', 'service.lghs-agent',
                    'service.lghs-command-executor', 'storage.root-writable',
                    'power.undervoltage', 'hardware.throttling', 'transport.controller',
                } else 'warning',
                'observed': True,
                'expected': True,
                'remediation': '',
            }
            for check_id in DEFAULT_REQUIRED_CHECKS
        ],
    }


class StructuredHealthGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = FleetDB(Path(self.tmp.name) / 'fleet.db')
        self.db.initialize()
        self.old = 'a' * 40
        self.target = 'b' * 40
        self.db.update_device_inventory('CS-001', current_commit=self.old, current_version='0.5.1', health_state='healthy', now=900)

    def tearDown(self):
        self.tmp.cleanup()

    def _telemetry(self, report, received_at=1000):
        self.db.record_telemetry(
            'CS-001',
            {'health_report': report, 'health': {}, 'metrics': {}},
            received_at=received_at,
            sent_at=received_at,
            agent_version='0.6.0-dev',
            protocol=1,
            boot_id='boot-1',
            sequence=int(received_at),
        )

    def _completed_deployment(self, deployment_id='dep-health', *, auto=False):
        freeze_deployment(
            self.db,
            deployment_id=deployment_id,
            name='Structured health rollout',
            target_commit=self.target,
            selector={'device_id': 'CS-001'},
            policy={'auto_advance': auto},
            strategy={'type': 'all-at-once', 'health_gate': {'max_report_age_seconds': 45}},
            now=900,
        )
        command_id = dispatch_phase(self.db, deployment_id, 0, now=910)[0]
        for state in ('received', 'accepted', 'running', 'succeeded'):
            self.db.transition_command(command_id, state, now={'received': 911, 'accepted': 912, 'running': 913, 'succeeded': 914}[state])
        with self.db.transaction() as db:
            db.execute(
                "UPDATE deployment_executions SET state='succeeded',stage='Complete',completed_at=914,updated_at=914 WHERE deployment_id=? AND device_id='CS-001'",
                (deployment_id,),
            )
        self.db.update_device_inventory('CS-001', current_commit=self.target, health_state='healthy', now=915)
        return command_id

    def test_structured_gate_passes_when_required_checks_are_fresh(self):
        self._telemetry(pass_report(), received_at=1000)
        result = device_health_gate(self.db, 'CS-001', strategy={'health_gate': {'max_report_age_seconds': 45}}, now=1010)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['mode'], 'structured-v2')
        self.assertEqual(result['blocked_checks'], [])

    def test_required_failure_is_reason_aware(self):
        report = pass_report()
        failing = next(item for item in report['checks'] if item['id'] == 'storage.root-writable')
        failing.update({'state': 'fail', 'observed': True, 'expected': False, 'remediation': 'inspect:filesystem'})
        self._telemetry(report, received_at=1000)
        result = device_health_gate(self.db, 'CS-001', strategy={}, now=1005)
        self.assertFalse(result['allowed'])
        self.assertEqual(result['blocked_checks'][0]['id'], 'storage.root-writable')
        self.assertIn('storage.root-writable', result['reason'])

    def test_stale_report_blocks_even_when_checks_pass(self):
        self._telemetry(pass_report(), received_at=1000)
        result = device_health_gate(self.db, 'CS-001', strategy={'health_gate': {'max_report_age_seconds': 30}}, now=1040)
        self.assertFalse(result['allowed'])
        self.assertEqual(result['blocked_checks'][0]['id'], 'telemetry.freshness')

    def test_legacy_device_falls_back_to_aggregate_health(self):
        result = device_health_gate(self.db, 'CS-001', strategy={'require_health': 'healthy'}, now=1000)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['mode'], 'legacy')

    def test_phase_gate_exposes_per_device_health_details(self):
        self._completed_deployment()
        report = pass_report()
        next(item for item in report['checks'] if item['id'] == 'clock.synchronized')['state'] = 'fail'
        self._telemetry(report, received_at=1000)
        gate = phase_gate(self.db, 'dep-health', 0, now=1010)
        self.assertEqual(gate['state'], 'waiting')
        self.assertEqual(gate['health_blocked'], ['CS-001'])
        blocked = gate['health_details']['CS-001']['blocked_checks']
        self.assertEqual(blocked[0]['id'], 'clock.synchronized')
        self.assertIn('CS-001', gate['reason'])

    def test_gate_transition_and_wave_actions_are_audited(self):
        freeze_deployment(
            self.db,
            deployment_id='dep-audit',
            name='Audit rollout',
            target_commit=self.target,
            selector={'device_id': 'CS-001'},
            policy={'auto_advance': True},
            strategy={'type': 'all-at-once', 'health_gate': {'max_report_age_seconds': 45}},
            now=900,
        )
        first = reconcile_deployment(self.db, 'dep-audit', now=910)
        self.assertEqual(first['action'], 'dispatched')
        cid = first['command_ids'][0]
        for state, stamp in (('received', 911), ('accepted', 912), ('running', 913), ('succeeded', 914)):
            self.db.transition_command(cid, state, now=stamp)
        with self.db.transaction() as db:
            db.execute("UPDATE deployment_executions SET state='succeeded',stage='Complete',completed_at=914,updated_at=914 WHERE deployment_id='dep-audit' AND device_id='CS-001'")
        self.db.update_device_inventory('CS-001', current_commit=self.target, health_state='healthy', now=915)
        self._telemetry(pass_report(), received_at=916)
        result = reconcile_deployment(self.db, 'dep-audit', now=917)
        self.assertEqual(result['action'], 'completed')
        with self.db.connect() as db:
            rows = db.execute("SELECT kind,detail_json FROM audit_events WHERE kind IN ('deployment-wave','deployment-gate') ORDER BY id").fetchall()
        text = '\n'.join(str(row['kind']) + ':' + str(row['detail_json']) for row in rows)
        self.assertIn('deployment-wave', text)
        self.assertIn('dispatched', text)
        self.assertIn('deployment-gate', text)
        self.assertIn('gate-transition', text)
        self.assertIn('completed', text)


class AgentHealthSchemaTests(unittest.TestCase):
    def test_agent_health_v2_separates_current_and_historical_power_faults(self):
        agent = load_agent()
        agent.clock_synced = lambda: True
        agent.failed_systemd_units = lambda: []
        agent.controller_transport_state = lambda: {
            'last_success_at': 1000,
            'last_error_at': None,
            'last_error': '',
            'age_seconds': 1,
            'fresh': True,
            'max_age_seconds': 30,
        }
        status = {
            'health': {
                'throttled_raw': '0x50000',
                'undervoltage_now': False,
                'undervoltage_occurred': True,
                'throttled_now': False,
                'throttled_occurred': True,
                'reboot_required': False,
            },
            'services': {
                'NetworkManager.service': 'active',
                'ssh.service': 'active',
                'lghs-policy.service': 'active',
                'lghs-agent.service': 'active',
                'lghs-command-executor.service': 'active',
            },
        }
        sample = {
            'temp_c': 45.0,
            'mem_pct': 20.0,
            'disk_pct': 30.0,
            'inode_pct': 5.0,
            'root_readonly': False,
            'wifi': {'signal_dbm': -55.0},
        }
        report = agent.structured_health(status, sample)
        self.assertEqual(report['health_version'], 2)
        checks = {item['id']: item for item in report['checks']}
        for check_id in DEFAULT_REQUIRED_CHECKS:
            self.assertIn(check_id, checks)
        self.assertEqual(checks['power.undervoltage']['state'], 'pass')
        self.assertEqual(checks['power.undervoltage-history']['state'], 'fail')
        self.assertEqual(checks['hardware.throttling']['state'], 'pass')
        self.assertEqual(checks['hardware.throttling-history']['state'], 'fail')
        self.assertEqual(checks['storage.root-writable']['state'], 'pass')
        self.assertEqual(checks['transport.controller']['state'], 'pass')


if __name__ == '__main__':
    unittest.main()
