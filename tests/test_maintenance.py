import importlib.machinery
import importlib.util
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from controller.lghs.database import FleetDB
from controller.lghs.maintenance import (
    cancel_reboot_schedule,
    create_reboot_schedule,
    get_reboot_schedule,
    maintenance_state,
    reconcile_reboot_schedule,
    set_device_policy,
    set_group_policy,
)
from controller.lghs.protocol import ALLOWED_COMMANDS

ROOT = Path(__file__).resolve().parents[1]


def epoch(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo('UTC')).timestamp()


def load_executor():
    path = ROOT / 'student' / 'lghs-command-executor'
    loader = importlib.machinery.SourceFileLoader('maintenance_test_executor', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = FleetDB(Path(self.tmp.name) / 'fleet.db')
        self.db.initialize()
        self.db.upsert_device('CS-001', boot_id='boot-a', last_seen=1000)
        self.db.upsert_device('CS-002', boot_id='boot-z', last_seen=1000)
        self.db.create_group('Room 101', group_id='room101', now=1000)
        self.db.create_group('After Hours', group_id='after-hours', now=1000)
        self.db.add_device_to_group('CS-001', 'room101', now=1000)
        self.db.add_device_to_group('CS-001', 'after-hours', now=1000)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cross_midnight_window_and_group_intersection(self):
        set_group_policy(self.db, 'room101', {
            'timezone': 'UTC',
            'windows': [{'days': ['mon'], 'start': '22:00', 'end': '06:00'}],
        }, now=1000)
        set_group_policy(self.db, 'after-hours', {
            'timezone': 'UTC',
            'windows': [{'days': ['tue'], 'start': '00:00', 'end': '04:00'}],
        }, now=1000)

        inside = maintenance_state(self.db, 'CS-001', now=epoch('2026-09-01T01:00:00'))
        self.assertTrue(inside['allowed'])
        self.assertEqual(len(inside['policies']), 2)

        blocked = maintenance_state(self.db, 'CS-001', now=epoch('2026-09-01T05:00:00'))
        self.assertFalse(blocked['allowed'])
        self.assertIsNotNone(blocked['next_open_at'])

    def test_device_policy_overrides_group_policies(self):
        set_group_policy(self.db, 'room101', {
            'timezone': 'UTC',
            'windows': [{'days': ['tue'], 'start': '00:00', 'end': '01:00'}],
        }, now=1000)
        set_group_policy(self.db, 'after-hours', {
            'timezone': 'UTC',
            'windows': [{'days': ['tue'], 'start': '00:00', 'end': '01:00'}],
        }, now=1000)
        set_device_policy(self.db, 'CS-001', {
            'timezone': 'UTC',
            'windows': [{'days': ['tue'], 'start': '05:00', 'end': '06:00'}],
        }, now=1000)

        state = maintenance_state(self.db, 'CS-001', now=epoch('2026-09-01T05:30:00'))
        self.assertTrue(state['allowed'])
        self.assertEqual([(x['scope'], x['id']) for x in state['policies']], [('device', 'CS-001')])

    def test_reboot_dispatch_and_boot_id_verification(self):
        schedule = create_reboot_schedule(
            self.db,
            selector={'device_id': 'CS-001'},
            mode='at',
            scheduled_at=1100,
            schedule_id='reboot-test',
            created_by='tester',
            now=1000,
        )
        self.assertEqual(schedule['state'], 'queued')
        early = reconcile_reboot_schedule(self.db, 'reboot-test', now=1050)
        self.assertEqual(early['actions'], [])

        dispatched = reconcile_reboot_schedule(self.db, 'reboot-test', now=1100)
        action = dispatched['actions'][0]
        self.assertEqual(action['action'], 'dispatched')
        cid = action['command_id']
        self.assertEqual(self.db.get_command(cid)['action'], 'reboot')
        self.db.transition_command(cid, 'accepted', now=1101)

        self.db.upsert_device('CS-001', boot_id='boot-b', last_seen=1110)
        verified = reconcile_reboot_schedule(self.db, 'reboot-test', now=1110)
        self.assertEqual(verified['actions'][0]['action'], 'verified')
        stored = get_reboot_schedule(self.db, 'reboot-test')
        self.assertEqual(stored['state'], 'succeeded')
        self.assertEqual(stored['executions']['CS-001']['boot_id_after'], 'boot-b')
        self.assertEqual(self.db.get_command(cid)['state'], 'succeeded')

    def test_cancel_before_local_acceptance(self):
        create_reboot_schedule(
            self.db,
            selector={'device_id': 'CS-001'},
            mode='at',
            scheduled_at=1000,
            schedule_id='reboot-cancel',
            now=1000,
        )
        dispatched = reconcile_reboot_schedule(self.db, 'reboot-cancel', now=1000)
        cid = dispatched['actions'][0]['command_id']
        result = cancel_reboot_schedule(self.db, 'reboot-cancel', actor='tester', now=1001)
        self.assertEqual(result['state'], 'canceled')
        self.assertEqual(result['canceled_devices'], ['CS-001'])
        self.assertEqual(self.db.get_command(cid)['state'], 'canceled')

    def test_maintenance_mode_waits_for_window(self):
        set_device_policy(self.db, 'CS-001', {
            'timezone': 'UTC',
            'windows': [{'days': ['tue'], 'start': '05:00', 'end': '06:00'}],
        }, now=1000)
        create_reboot_schedule(
            self.db,
            selector={'device_id': 'CS-001'},
            mode='maintenance',
            not_before=epoch('2026-09-01T00:00:00'),
            schedule_id='reboot-window',
            now=epoch('2026-09-01T00:00:00'),
        )
        waiting = reconcile_reboot_schedule(self.db, 'reboot-window', now=epoch('2026-09-01T04:59:00'))
        self.assertEqual(waiting['actions'], [])
        dispatched = reconcile_reboot_schedule(self.db, 'reboot-window', now=epoch('2026-09-01T05:00:00'))
        self.assertEqual(dispatched['actions'][0]['action'], 'dispatched')

    def test_reboot_is_typed_executor_action(self):
        self.assertIn('reboot', ALLOWED_COMMANDS)
        executor = load_executor()
        command = executor.action_command('reboot', {'schedule_id': 'sched-1', 'reason': 'maintenance'}, 'cmd-1')
        self.assertTrue(any('systemd-run' in part for part in command))
        self.assertEqual(command[-1], 'reboot')
        self.assertNotIn('sh', command)
        with self.assertRaises(ValueError):
            executor.action_command('reboot', {'schedule_id': ''}, 'cmd-2')


if __name__ == '__main__':
    unittest.main()
