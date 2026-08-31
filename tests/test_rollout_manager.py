#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path

from controller.lghs.database import FleetDB
from controller.lghs.rollout import freeze_deployment
from controller.lghs.rollout_manager import load_runtime, reconcile_deployment


class RolloutManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = FleetDB(Path(self.tmp.name) / 'fleet.db')
        self.store.initialize()
        self.old = 'a' * 40
        self.target = 'b' * 40
        for device in ('CS-001', 'CS-002', 'CS-003', 'CS-004'):
            self.store.update_device_inventory(
                device,
                current_commit=self.old,
                current_version='0.5.1',
                health_state='healthy',
            )
        self.store.set_device_tags('CS-003', ['ring:canary'])

    def tearDown(self):
        self.tmp.cleanup()

    def _create_auto(self, deployment_id='dep-auto'):
        return freeze_deployment(
            self.store,
            deployment_id=deployment_id,
            name='Automatic phased rollout',
            target_commit=self.target,
            selector={'device_ids': ['CS-001', 'CS-002', 'CS-003', 'CS-004']},
            policy={'auto_advance': True},
            strategy={
                'type': 'phased',
                'canary_count': 1,
                'canary_tag': 'ring:canary',
                'wave_percentages': [50, 100],
                'soak_seconds': 10,
                'require_health': 'healthy',
            },
        )

    def _succeed_phase(self, deployment_id, phase):
        rows = [row for row in self.store.list_deployment_executions(deployment_id) if row['phase'] == phase]
        for row in rows:
            self.assertIsNotNone(row['command_id'])
            cid = row['command_id']
            self.store.transition_command(cid, 'delivered')
            self.store.transition_command(cid, 'received')
            self.store.transition_command(cid, 'accepted')
            self.store.transition_command(cid, 'running')
            self.store.transition_command(cid, 'succeeded', stage='Complete', message='installed')
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE deployment_executions SET state='succeeded',stage='Complete' WHERE deployment_id=? AND device_id=?",
                    (deployment_id, row['device_id']),
                )
            self.store.update_device_inventory(row['device_id'], current_commit=self.target, health_state='healthy')
        return rows

    def test_auto_manager_dispatches_canary_then_soaks_before_next_wave(self):
        result = self._create_auto()
        first = reconcile_deployment(self.store, 'dep-auto', now=100)
        self.assertEqual(first['action'], 'dispatched')
        self.assertEqual(first['phase'], 0)
        self.assertEqual(result['phases'][0], ['CS-003'])

        self._succeed_phase('dep-auto', 0)
        soak = reconcile_deployment(self.store, 'dep-auto', now=101)
        self.assertEqual(soak['action'], 'soaking')
        self.assertEqual(soak['remaining_seconds'], 10.0)
        self.assertEqual(load_runtime(self.store, 'dep-auto')['next_action_at'], 111)

        still = reconcile_deployment(self.store, 'dep-auto', now=110)
        self.assertEqual(still['action'], 'soaking')
        rows = self.store.list_deployment_executions('dep-auto')
        self.assertTrue(all(row['command_id'] is None for row in rows if row['phase'] == 1))

        advanced = reconcile_deployment(self.store, 'dep-auto', now=111)
        self.assertEqual(advanced['action'], 'advanced')
        self.assertEqual(advanced['phase'], 1)
        rows = self.store.list_deployment_executions('dep-auto')
        self.assertTrue(all(row['command_id'] for row in rows if row['phase'] == 1))
        self.assertTrue(all(row['command_id'] is None for row in rows if row['phase'] > 1))

    def test_health_regression_resets_soak_timer(self):
        result = self._create_auto('dep-health')
        reconcile_deployment(self.store, 'dep-health', now=200)
        self._succeed_phase('dep-health', 0)
        soak = reconcile_deployment(self.store, 'dep-health', now=201)
        self.assertEqual(soak['action'], 'soaking')
        canary = result['phases'][0][0]

        self.store.update_device_inventory(canary, health_state='warning')
        waiting = reconcile_deployment(self.store, 'dep-health', now=205)
        self.assertEqual(waiting['action'], 'waiting')
        runtime = load_runtime(self.store, 'dep-health')
        self.assertIsNone(runtime['ready_since'])
        self.assertIsNone(runtime['next_action_at'])

        self.store.update_device_inventory(canary, health_state='healthy')
        restarted = reconcile_deployment(self.store, 'dep-health', now=206)
        self.assertEqual(restarted['action'], 'soaking')
        self.assertEqual(load_runtime(self.store, 'dep-health')['next_action_at'], 216)
        self.assertEqual(reconcile_deployment(self.store, 'dep-health', now=215)['action'], 'soaking')
        self.assertEqual(reconcile_deployment(self.store, 'dep-health', now=216)['action'], 'advanced')

    def test_canary_failure_pauses_without_waiting_for_soak(self):
        self._create_auto('dep-pause')
        reconcile_deployment(self.store, 'dep-pause', now=300)
        row = next(row for row in self.store.list_deployment_executions('dep-pause') if row['phase'] == 0)
        self.store.transition_command(row['command_id'], 'failed', stage='Install failed', message='simulated')
        with self.store.transaction() as db:
            db.execute(
                "UPDATE deployment_executions SET state='failed',stage='Install failed',error_code='FAILED' WHERE deployment_id=? AND device_id=?",
                ('dep-pause', row['device_id']),
            )
        paused = reconcile_deployment(self.store, 'dep-pause', now=301)
        self.assertEqual(paused['action'], 'paused')
        deployment = self.store.get_deployment('dep-pause')
        self.assertEqual(deployment['state'], 'paused')
        self.assertEqual(deployment['paused_reason'], 'canary failure')
        self.assertEqual(load_runtime(self.store, 'dep-pause')['paused_reason'], 'canary failure')

    def test_manual_deployment_is_not_touched(self):
        freeze_deployment(
            self.store,
            deployment_id='dep-manual',
            name='Manual rollout',
            target_commit=self.target,
            selector={'device_id': 'CS-001'},
            policy={'auto_advance': False},
            strategy={'type': 'all-at-once'},
        )
        result = reconcile_deployment(self.store, 'dep-manual', now=400)
        self.assertEqual(result['action'], 'manual')
        execution = self.store.list_deployment_executions('dep-manual')[0]
        self.assertIsNone(execution['command_id'])


if __name__ == '__main__':
    unittest.main()
