#!/usr/bin/env python3
import json,tempfile,unittest
from pathlib import Path
from controller.lghs.audit import record_batches
from controller.lghs.database import FleetDB

class AuditIngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=FleetDB(Path(self.tmp.name)/'fleet.db');self.store.initialize()
    def tearDown(self):self.tmp.cleanup()
    def test_records_and_acks_bounded_batch(self):
        ack=record_batches(self.store,'CS-999',[{'kind':'sudo','inode':9,'offset':100,'next_offset':120,'text':'hello\n'}])
        self.assertEqual(ack,{'sudo':{'inode':9,'next_offset':120}})
        with self.store.connect() as db:
            rows=db.execute("SELECT kind,sequence,detail_json FROM audit_events WHERE device_id='CS-999'").fetchall()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['kind'],'sudo');self.assertEqual(rows[0]['sequence'],100);self.assertEqual(json.loads(rows[0]['detail_json'])['next_offset'],120)
    def test_duplicate_offset_is_idempotent(self):
        batch={'kind':'audit','inode':2,'offset':0,'next_offset':4,'text':'abc\n'}
        record_batches(self.store,'CS-999',[batch]);record_batches(self.store,'CS-999',[batch])
        with self.store.connect() as db:count=db.execute("SELECT COUNT(*) FROM audit_events WHERE device_id='CS-999' AND kind='audit'").fetchone()[0]
        self.assertEqual(count,1)
    def test_unknown_kind_ignored(self):
        self.assertEqual(record_batches(self.store,'CS-999',[{'kind':'shadow','offset':0,'next_offset':2,'text':'x'}]),{})
if __name__=='__main__':unittest.main()
