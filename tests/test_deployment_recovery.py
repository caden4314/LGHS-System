#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from controller.lghs.database import FleetDB
from controller.lghs.recovery import cancel_remaining, create_rollback, resume_deployment, retry_failed
from controller.lghs.rollout import StrategyError, dispatch_phase, freeze_deployment


class DeploymentRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = FleetDB(Path(self.tmp.name) / 'fleet.db')
        self.store.initialize()
        self.old = 'a' * 40
        self.older = 'c' * 40
        self.target = 'b' * 40
        for device in ('CS-001', 'CS-002', 'CS-003', 'CS-004'):
            self.store.update_device_inventory(
                device,
                current_commit=self.old,
                current_version='0.5.1',
                health_state='healthy',
            )

    def tearDown(self):
        self.tmp.cleanup()

    def _deployment(self, deployment_id='dep-recovery', phased=False):
        result = freeze_deployment(
            self.store,
            deployment_id=deployment_id,
            name='Recovery test',
            target_commit=self.target,
            selector={'device_ids': ['CS-001', 'CS-002', 'CS-003', 'CS-004']},
            policy={'auto_advance': phased},
            strategy={
                'type': 'phased' if phased else 'all-at-once',
                'canary_count': 1,
                'wave_percentages': [50, 100],
                'soak_seconds': 0,
            } if phased else {'type': 'all-at-once'},
        )
        return result

    def _fail(self, deployment_id, device):
        row = next(x for x in self.store.list_deployment_executions(deployment_id) if x['device_id'] == device)
        cid = row['command_id']
        self.assertIsNotNone(cid)
        self.store.transition_command(cid, 'delivered')
        self.store.transition_command(cid, 'received')
        self.store.transition_command(cid, 'accepted')
        self.store.transition_command(cid, 'running')
        self.store.transition_command(cid, 'failed', stage='Install failed', message='simulated')
        with self.store.transaction() as db:
            db.execute(
                "UPDATE deployment_executions SET state='failed',stage='Install failed',completed_at=1,error_code='FAILED',error_message='simulated' WHERE deployment_id=? AND device_id=?",
                (deployment_id, device),
            )
            db.execute("UPDATE deployments SET state='paused',paused_reason='canary failure' WHERE deployment_id=?", (deployment_id,))
        return cid

    def test_retry_failed_creates_new_command_and_increments_attempt(self):
        self._deployment(phased=True)
        dispatch_phase(self.store, 'dep-recovery', 0, now=10)
        device = next(x['device_id'] for x in self.store.list_deployment_executions('dep-recovery') if x['phase'] == 0)
        old_cid = self._fail('dep-recovery', device)

        result = retry_failed(self.store, 'dep-recovery', actor='cs_admin', now=20)
        self.assertEqual(result['devices'], [device])
        self.assertEqual(len(result['command_ids']), 1)
        self.assertNotEqual(result['command_ids'][0], old_cid)
        row = next(x for x in self.store.list_deployment_executions('dep-recovery') if x['device_id'] == device)
        self.assertEqual(row['state'], 'queued')
        self.assertEqual(row['attempt'], 1)
        self.assertIsNone(row['error_code'])
        self.assertEqual(self.store.get_deployment('dep-recovery')['state'], 'running')
        payload = json.loads(self.store.get_command(row['command_id'])['payload_json'])
        self.assertEqual(payload['retry_of'], old_cid)
        self.assertEqual(payload['target_commit'], self.target)

    def test_resume_refuses_while_pause_condition_is_still_active(self):
        self._deployment(phased=True)
        dispatch_phase(self.store, 'dep-recovery', 0)
        device = next(x['device_id'] for x in self.store.list_deployment_executions('dep-recovery') if x['phase'] == 0)
        self._fail('dep-recovery', device)
        with self.assertRaises(StrategyError):
            resume_deployment(self.store, 'dep-recovery', actor='cs_admin')

    def test_cancel_remaining_cancels_undispatched_and_preaccept_commands_only(self):
        self._deployment(phased=True)
        dispatch_phase(self.store, 'dep-recovery', 0, now=10)
        rows = self.store.list_deployment_executions('dep-recovery')
        canary = next(x for x in rows if x['phase'] == 0)
        self.store.transition_command(canary['command_id'], 'delivered', now=11)
        result = cancel_remaining(self.store, 'dep-recovery', actor='cs_admin', now=12)
        self.assertIn(canary['device_id'], result['canceled_devices'])
        self.assertEqual(result['continuing_devices'], [])
        self.assertEqual(self.store.get_command(canary['command_id'])['state'], 'canceled')
        rows = self.store.list_deployment_executions('dep-recovery')
        self.assertTrue(all(x['state'] == 'canceled' for x in rows))
        self.assertEqual(self.store.get_deployment('dep-recovery')['state'], 'canceled')

    def test_cancel_remaining_does_not_interrupt_accepted_work(self):
        self._deployment(phased=True)
        dispatch_phase(self.store, 'dep-recovery', 0, now=10)
        canary = next(x for x in self.store.list_deployment_executions('dep-recovery') if x['phase'] == 0)
        self.store.transition_command(canary['command_id'], 'delivered', now=11)
        self.store.transition_command(canary['command_id'], 'received', now=12)
        self.store.transition_command(canary['command_id'], 'accepted', now=13)
        with self.store.transaction() as db:
            db.execute("UPDATE deployment_executions SET state='accepted' WHERE deployment_id=? AND device_id=?", ('dep-recovery', canary['device_id']))
        result = cancel_remaining(self.store, 'dep-recovery', actor='cs_admin', now=14)
        self.assertEqual(result['continuing_devices'], [canary['device_id']])
        self.assertEqual(self.store.get_command(canary['command_id'])['state'], 'accepted')
        later = [x for x in self.store.list_deployment_executions('dep-recovery') if x['phase'] > 0]
        self.assertTrue(later)
        self.assertTrue(all(x['state'] == 'canceled' for x in later))

    def test_rollback_uses_recorded_previous_commits_and_skips_unsafe_devices(self):
        self._deployment(phased=False)
        dispatch_phase(self.store, 'dep-recovery', 0)
        with self.store.transaction() as db:
            db.execute("UPDATE deployment_executions SET previous_commit=? WHERE deployment_id=? AND device_id='CS-004'", (self.older, 'dep-recovery'))
        for device in ('CS-001', 'CS-002', 'CS-003', 'CS-004'):
            self.store.update_device_inventory(device, current_commit=self.target, health_state='healthy')
        self.store.update_device_inventory('CS-003', current_commit='d' * 40, health_state='healthy')

        result = create_rollback(self.store, 'dep-recovery', actor='cs_admin', dispatch=False, now=50)
        self.assertEqual(len(result['rollbacks']), 2)
        by_commit = {item['target_commit']: item for item in result['rollbacks']}
        self.assertEqual(by_commit[self.old]['devices'], ['CS-001', 'CS-002'])
        self.assertEqual(by_commit[self.older]['devices'], ['CS-004'])
        self.assertEqual(result['skipped']['CS-003'], 'current-commit-does-not-match-deployment-target')
        for item in result['rollbacks']:
            dep = self.store.get_deployment(item['deployment_id'])
            self.assertEqual(dep['target_commit'], item['target_commit'])
            self.assertEqual(dep['state'], 'queued')
            self.assertTrue(all(x['command_id'] is None for x in self.store.list_deployment_executions(item['deployment_id'])))

    def test_recovery_actions_are_audited(self):
        self._deployment(phased=True)
        dispatch_phase(self.store, 'dep-recovery', 0)
        device = next(x['device_id'] for x in self.store.list_deployment_executions('dep-recovery') if x['phase'] == 0)
        self._fail('dep-recovery', device)
        retry_failed(self.store, 'dep-recovery', actor='cs_admin', now=20)
        with self.store.connect() as db:
            rows = db.execute("SELECT detail_json FROM audit_events WHERE kind='deployment' ORDER BY id").fetchall()
        self.assertTrue(rows)
        detail = json.loads(rows[-1]['detail_json'])
        self.assertEqual(detail['action'], 'retry-failed')
        self.assertEqual(detail['actor'], 'cs_admin')


if __name__ == '__main__':
    unittest.main()
