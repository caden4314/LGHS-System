#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path

from controller.lghs.database import FleetDB
from controller.lghs.maintenance import cancel_reboot_schedule, create_reboot_schedule, reconcile_reboot_schedule


class RebootCancelSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = FleetDB(Path(self.tmp.name) / 'fleet.db')
        self.db.initialize()
        self.db.upsert_device('CS-001', boot_id='boot-a', last_seen=1000)

    def tearDown(self):
        self.tmp.cleanup()

    def test_delivered_reboot_is_not_claimed_canceled(self):
        create_reboot_schedule(
            self.db,
            selector={'device_id': 'CS-001'},
            mode='at',
            scheduled_at=1000,
            schedule_id='delivered-reboot',
            now=1000,
        )
        dispatched = reconcile_reboot_schedule(self.db, 'delivered-reboot', now=1000)
        cid = dispatched['actions'][0]['command_id']
        delivered = self.db.commands_for_delivery('CS-001', now=1001)
        self.assertEqual([row['id'] for row in delivered], [cid])
        self.assertEqual(self.db.get_command(cid)['state'], 'delivered')

        canceled = cancel_reboot_schedule(self.db, 'delivered-reboot', actor='tester', now=1002)
        self.assertEqual(canceled['state'], 'canceling')
        self.assertEqual(canceled['canceled_devices'], [])
        self.assertEqual(canceled['continuing_devices'], ['CS-001'])
        self.assertEqual(self.db.get_command(cid)['state'], 'delivered')

    def test_reboot_execution_dispatch_is_audited(self):
        create_reboot_schedule(
            self.db,
            selector={'device_id': 'CS-001'},
            mode='at',
            scheduled_at=2000,
            schedule_id='audit-reboot',
            now=2000,
        )
        reconcile_reboot_schedule(self.db, 'audit-reboot', now=2000)
        with self.db.connect() as db:
            rows = db.execute("SELECT kind,device_id,detail_json FROM audit_events WHERE kind='reboot-execution'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['device_id'], 'CS-001')
        self.assertIn('dispatched', rows[0]['detail_json'])
        self.assertIn('audit-reboot', rows[0]['detail_json'])


if __name__ == '__main__':
    unittest.main()
