#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from controller.lghs.database import FleetDB
from controller.lghs.rollout import (
    TargetError,
    advance_rollout,
    dispatch_phase,
    freeze_deployment,
    phase_gate,
    plan_phases,
    resolve_targets,
)


class FleetRolloutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = FleetDB(Path(self.tmp.name) / 'fleet.db')
        self.store.initialize()
        self.old = 'a' * 40
        self.target = 'b' * 40
        for index, device in enumerate(('CS-001', 'CS-002', 'CS-003', 'CS-004', 'CS-005')):
            self.store.update_device_inventory(
                device,
                hostname=device,
                role='student',
                model='Raspberry Pi 5 Model B',
                ram_mb=8192,
                serial=f'serial-{index}',
                current_commit=self.old,
                current_version='0.5.1',
                health_state='healthy',
            )
        self.store.create_group('Room 101', group_id='room101')
        for device in ('CS-001', 'CS-002', 'CS-003', 'CS-004'):
            self.store.add_device_to_group(device, 'room101')
        self.store.set_device_tags('CS-003', ['ring:canary', 'room:101'])
        self.store.set_device_tags('CS-004', ['room:101'])

    def tearDown(self):
        self.tmp.cleanup()

    def test_target_resolution_is_exact_and_nonempty(self):
        selector, devices = resolve_targets(self.store, {'group_id': 'room101'})
        self.assertEqual(selector, {'group_id': 'room101'})
        self.assertEqual(devices, ['CS-001', 'CS-002', 'CS-003', 'CS-004'])
        _, tagged = resolve_targets(self.store, {'tag': 'ring:canary'})
        self.assertEqual(tagged, ['CS-003'])
        _, explicit = resolve_targets(self.store, {'device_ids': ['CS-002', 'CS-001', 'CS-002']})
        self.assertEqual(explicit, ['CS-001', 'CS-002'])
        with self.assertRaises(TargetError):
            resolve_targets(self.store, {'group_id': 'missing'})
        with self.assertRaises(TargetError):
            resolve_targets(self.store, {'device_id': 'CS-001', 'tag': 'ring:canary'})

    def test_frozen_membership_does_not_change_when_group_changes(self):
        result = freeze_deployment(
            self.store,
            deployment_id='dep-frozen',
            name='Frozen Room 101',
            target_commit=self.target,
            target_version='0.6.0-dev',
            selector={'group_id': 'room101'},
            strategy={'type': 'all-at-once'},
        )
        self.assertEqual(result['target']['resolved_devices'], ['CS-001', 'CS-002', 'CS-003', 'CS-004'])
        self.store.add_device_to_group('CS-005', 'room101')
        deployment = self.store.get_deployment('dep-frozen')
        frozen = json.loads(deployment['target_json'])
        self.assertEqual(frozen['resolved_devices'], ['CS-001', 'CS-002', 'CS-003', 'CS-004'])
        executions = self.store.list_deployment_executions('dep-frozen')
        self.assertEqual([row['device_id'] for row in executions], ['CS-001', 'CS-002', 'CS-003', 'CS-004'])
        self.assertEqual(self.store.get_device('CS-005')['desired_commit'], None)
        for device in frozen['resolved_devices']:
            self.assertEqual(self.store.get_device(device)['desired_commit'], self.target)

    def test_phased_plan_prefers_canary_tag_and_uses_cumulative_waves(self):
        normalized, phases = plan_phases(
            self.store,
            ['CS-001', 'CS-002', 'CS-003', 'CS-004', 'CS-005'],
            {
                'type': 'phased',
                'canary_count': 1,
                'canary_tag': 'ring:canary',
                'wave_percentages': [40, 60, 100],
                'soak_seconds': 300,
            },
        )
        self.assertEqual(normalized['type'], 'phased')
        self.assertEqual(phases[0], ['CS-003'])
        self.assertEqual(len(phases[1]), 1)
        self.assertEqual(len(phases[2]), 1)
        self.assertEqual(len(phases[3]), 2)
        flattened = [device for phase in sorted(phases) for device in phases[phase]]
        self.assertEqual(sorted(flattened), ['CS-001', 'CS-002', 'CS-003', 'CS-004', 'CS-005'])

    def test_only_requested_phase_is_dispatched(self):
        result = freeze_deployment(
            self.store,
            deployment_id='dep-phased',
            name='Phased Room 101',
            target_commit=self.target,
            selector={'group_id': 'room101'},
            strategy={'type': 'phased', 'canary_count': 1, 'canary_tag': 'ring:canary', 'wave_percentages': [50, 100]},
        )
        self.assertEqual(result['phases'][0], ['CS-003'])
        command_ids = dispatch_phase(self.store, 'dep-phased', 0, now=1000)
        self.assertEqual(len(command_ids), 1)
        rows = self.store.list_deployment_executions('dep-phased')
        canary = next(row for row in rows if row['device_id'] == 'CS-003')
        self.assertIsNotNone(canary['command_id'])
        self.assertTrue(all(row['command_id'] is None for row in rows if row['device_id'] != 'CS-003'))
        command = self.store.get_command(canary['command_id'])
        payload = json.loads(command['payload_json'])
        self.assertEqual(payload['target_commit'], self.target)
        self.assertEqual(payload['deployment_id'], 'dep-phased')
        self.assertEqual(payload['phase'], 0)

    def test_canary_failure_auto_pauses(self):
        freeze_deployment(
            self.store,
            deployment_id='dep-fail',
            name='Canary failure',
            target_commit=self.target,
            selector={'group_id': 'room101'},
            strategy={'type': 'phased', 'canary_count': 1, 'canary_tag': 'ring:canary', 'wave_percentages': [50, 100]},
        )
        dispatch_phase(self.store, 'dep-fail', 0)
        execution = self.store.list_deployment_executions('dep-fail')[0]
        self.store.transition_command(execution['command_id'], 'failed', stage='Install failed', message='simulated failure')
        with self.store.transaction() as db:
            db.execute("UPDATE deployment_executions SET state='failed',stage='Install failed',error_code='FAILED' WHERE deployment_id=? AND device_id=?", ('dep-fail', execution['device_id']))
        gate = phase_gate(self.store, 'dep-fail', 0)
        self.assertEqual(gate['state'], 'paused')
        self.assertEqual(gate['reason'], 'canary failure')
        status = advance_rollout(self.store, 'dep-fail')
        self.assertEqual(status['deployment']['state'], 'paused')
        self.assertEqual(self.store.get_deployment('dep-fail')['paused_reason'], 'canary failure')

    def test_success_requires_reported_target_commit_and_health_before_advance(self):
        result = freeze_deployment(
            self.store,
            deployment_id='dep-verify',
            name='Verify before wave 1',
            target_commit=self.target,
            selector={'group_id': 'room101'},
            strategy={'type': 'phased', 'canary_count': 1, 'canary_tag': 'ring:canary', 'wave_percentages': [50, 100]},
        )
        dispatch_phase(self.store, 'dep-verify', 0)
        canary_device = result['phases'][0][0]
        execution = next(row for row in self.store.list_deployment_executions('dep-verify') if row['device_id'] == canary_device)
        self.store.transition_command(execution['command_id'], 'delivered')
        self.store.transition_command(execution['command_id'], 'received')
        self.store.transition_command(execution['command_id'], 'accepted')
        self.store.transition_command(execution['command_id'], 'running')
        self.store.transition_command(execution['command_id'], 'succeeded', stage='Complete', message='installed')
        with self.store.transaction() as db:
            db.execute("UPDATE deployment_executions SET state='succeeded',stage='Complete' WHERE deployment_id=? AND device_id=?", ('dep-verify', canary_device))

        self.assertEqual(phase_gate(self.store, 'dep-verify', 0)['state'], 'waiting')
        self.store.update_device_inventory(canary_device, current_commit=self.target, health_state='warning')
        self.assertEqual(phase_gate(self.store, 'dep-verify', 0)['state'], 'waiting')
        self.store.update_device_inventory(canary_device, health_state='healthy')
        self.assertEqual(phase_gate(self.store, 'dep-verify', 0)['state'], 'ready')

        status = advance_rollout(self.store, 'dep-verify')
        self.assertEqual(status['active_phase'], 1)
        rows = self.store.list_deployment_executions('dep-verify')
        phase_one = [row for row in rows if row['phase'] == 1]
        self.assertTrue(phase_one)
        self.assertTrue(all(row['command_id'] for row in phase_one))
        later = [row for row in rows if row['phase'] > 1]
        self.assertTrue(all(row['command_id'] is None for row in later))

    def test_failure_threshold_allows_one_failure_in_large_wave_but_blocks_at_threshold(self):
        for index in range(6, 26):
            device = f'CS-{index:03d}'
            self.store.update_device_inventory(device, current_commit=self.old, current_version='0.5.1', health_state='healthy')
        _, devices = resolve_targets(self.store, {'all': True})
        result = freeze_deployment(
            self.store,
            deployment_id='dep-threshold',
            name='Threshold test',
            target_commit=self.target,
            selector={'all': True},
            strategy={'type': 'phased', 'canary_count': 1, 'wave_percentages': [100], 'failure_threshold_count': 2, 'failure_threshold_percent': 10},
        )
        self.assertEqual(len(result['target']['resolved_devices']), len(devices))
        phase = max(result['phases'])
        dispatch_phase(self.store, 'dep-threshold', phase)
        rows = [row for row in self.store.list_deployment_executions('dep-threshold') if row['phase'] == phase]
        self.assertGreaterEqual(len(rows), 20)
        failed = rows[0]
        with self.store.transaction() as db:
            db.execute("UPDATE deployment_executions SET state='failed' WHERE deployment_id=? AND device_id=?", ('dep-threshold', failed['device_id']))
            for row in rows[1:]:
                db.execute("UPDATE deployment_executions SET state='succeeded' WHERE deployment_id=? AND device_id=?", ('dep-threshold', row['device_id']))
        for row in rows[1:]:
            self.store.update_device_inventory(row['device_id'], current_commit=self.target, health_state='healthy')
        self.assertEqual(phase_gate(self.store, 'dep-threshold', phase)['state'], 'ready')
        second = rows[1]
        with self.store.transaction() as db:
            db.execute("UPDATE deployment_executions SET state='failed' WHERE deployment_id=? AND device_id=?", ('dep-threshold', second['device_id']))
        self.assertEqual(phase_gate(self.store, 'dep-threshold', phase)['state'], 'paused')


if __name__ == '__main__':
    unittest.main()
