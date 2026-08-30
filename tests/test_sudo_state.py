#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from controller.lghs.database import FleetDB
from controller.lghs.sudo_state import record_snapshot


class SudoStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = FleetDB(Path(self.tmp.name) / 'fleet.db')
        self.store.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_upserts_request_lifecycle(self):
        record_snapshot(self.store, 'CS-999', [{
            'id': 'req-1',
            'status': 'pending',
            'command': 'apt install python3-numpy',
            'requester': 'lg_cs_cont',
            'requested_epoch': 100,
            'expires_epoch': 200,
            'argv': ['apt', 'install', 'python3-numpy'],
        }])
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM sudo_requests WHERE request_id=?', ('req-1',)).fetchone()
            self.assertEqual(row['device_id'], 'CS-999')
            self.assertEqual(row['state'], 'pending')
            self.assertEqual(row['command'], 'apt install python3-numpy')
            self.assertEqual(json.loads(row['detail_json'])['requester'], 'lg_cs_cont')

        record_snapshot(self.store, 'CS-999', [{
            'id': 'req-1',
            'status': 'approved',
            'command': 'apt install python3-numpy',
            'requested_epoch': 100,
            'resolved_at': '2026-08-30T06:30:00+00:00',
            'approved_by': 'cs_admin',
        }])
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM sudo_requests WHERE request_id=?', ('req-1',)).fetchone()
            self.assertEqual(row['state'], 'approved')
            self.assertEqual(json.loads(row['detail_json'])['approved_by'], 'cs_admin')


if __name__ == '__main__':
    unittest.main()
