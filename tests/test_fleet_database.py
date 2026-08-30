#!/usr/bin/env python3
import json,tempfile,time,unittest
from pathlib import Path
from controller.lghs.database import FleetDB
from controller.lghs.protocol import ProtocolError,TelemetryEnvelope,normalize_command_state,state_can_advance

class ProtocolTests(unittest.TestCase):
    def test_state_normalization(self):
        self.assertEqual(normalize_command_state('pending'),'queued');self.assertEqual(normalize_command_state('complete'),'succeeded');self.assertTrue(state_can_advance('received','accepted'));self.assertFalse(state_can_advance('running','accepted'))
    def test_envelope(self):
        now=time.time();env=TelemetryEnvelope.from_mapping({'protocol':1,'agent_version':'0.5.0','device_id':'cs-999','boot_id':'boot-1','sequence':7,'sent_at':now,'payload':{'metrics':{'cpu_pct':12.3}}},now=now);self.assertEqual(env.device_id,'CS-999');self.assertEqual(env.sequence,7)
        with self.assertRaises(ProtocolError):TelemetryEnvelope.from_mapping({'protocol':2},now=now)

class FleetDBTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=FleetDB(self.root/'fleet.db');self.store.initialize()
    def tearDown(self):self.tmp.cleanup()
    def test_wal_and_schema(self):
        with self.store.connect() as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0].lower(),'wal');self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'2');tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name in {'devices','telemetry_latest','commands','command_events','warnings','warning_events','deployments','deployment_executions','sudo_requests','audit_events','notifications','settings'}:self.assertIn(name,tables)
    def test_telemetry_sequence_rejects_only_regression(self):
        self.store.record_telemetry('CS-999',{'x':1},received_at=100,sent_at=99,agent_version='0.5.0',protocol=1,boot_id='boot-a',sequence=10)
        self.store.record_telemetry('CS-999',{'x':2},received_at=101,sent_at=100,agent_version='0.5.0',protocol=1,boot_id='boot-a',sequence=10)
        with self.assertRaises(ValueError):self.store.record_telemetry('CS-999',{'x':3},received_at=102,sent_at=101,agent_version='0.5.0',protocol=1,boot_id='boot-a',sequence=9)
        self.store.record_telemetry('CS-999',{'x':4},received_at=103,sent_at=102,agent_version='0.5.0',protocol=1,boot_id='boot-b',sequence=0);self.assertEqual(self.store.latest_telemetry('CS-999')['boot_id'],'boot-b')
    def test_command_timeline_and_dedupe(self):
        cid=self.store.create_command('CS-999','lghs-update',command_id='cmd-1',now=10);self.assertEqual(self.store.create_command('CS-999','lghs-update',now=10.5),'cmd-1')
        for state,ts in [('delivered',11),('received',12),('accepted',13),('running',14),('succeeded',15)]:self.store.transition_command(cid,state,stage='Complete' if state=='succeeded' else None,progress=100 if state=='succeeded' else None,now=ts)
        row=self.store.get_command(cid);self.assertEqual(row['state'],'succeeded');self.assertEqual(row['accepted_at'],13);self.assertEqual(row['started_at'],14);self.assertEqual(row['completed_at'],15)
        with self.store.connect() as db:states=[r[0] for r in db.execute('SELECT state FROM command_events WHERE command_id=? ORDER BY id',(cid,))]
        self.assertEqual(states,['queued','delivered','received','accepted','running','succeeded'])
    def test_delivery_redelivers_until_accepted_and_times_out(self):
        cid=self.store.create_command('CS-999','lghs-update',command_id='cmd',now=10,deadline_at=20)
        first=self.store.commands_for_delivery('CS-999',now=11);self.assertEqual(first[0]['id'],cid);self.assertEqual(self.store.get_command(cid)['state'],'delivered')
        self.assertEqual(self.store.commands_for_delivery('CS-999',now=11.2),[])
        again=self.store.commands_for_delivery('CS-999',now=12.5);self.assertEqual(again[0]['id'],cid)
        self.store.transition_command(cid,'received',now=13);self.assertEqual(self.store.commands_for_delivery('CS-999',now=14.2)[0]['id'],cid)
        self.store.transition_command(cid,'accepted',now=15);self.assertEqual(self.store.commands_for_delivery('CS-999',now=16),[])
        late=self.store.create_command('CS-999','os-update',command_id='late',now=1,deadline_at=2);self.assertEqual(self.store.commands_for_delivery('CS-999',now=3),[]);self.assertEqual(self.store.get_command(late)['state'],'timed_out')
    def test_legacy_migration_and_export(self):
        registry=self.root/'fleet.json';cache=self.root/'cache.json';commands=self.root/'commands.json';export=self.root/'export.json'
        registry.write_text(json.dumps({'devices':{'CS-999':{'transport':'cloudflare','ssh_host':'ssh.example'}}}));cache.write_text(json.dumps({'devices':{'CS-999':{'received_at':9,'cpu_pct':12}}}));commands.write_text(json.dumps({'devices':{'CS-999':[{'id':'old','action':'lghs-update','state':'received','created_at':5,'updated_at':6}]}}))
        counts=self.store.migrate_legacy(registry=registry,cache=cache,commands=commands);self.assertEqual(counts['commands'],1);self.assertEqual(self.store.get_command('old')['state'],'received');self.store.export_legacy_commands(export);data=json.loads(export.read_text());self.assertEqual(data['devices']['CS-999'][0]['id'],'old')
    def test_warning_lifecycle(self):
        self.store.evaluate_health('CS-999',{'metrics':{'temp_c':82,'disk_pct':91},'health':{'undervoltage_occurred':True,'reboot_required':True}});warnings={w['kind']:w for w in self.store.list_warnings('CS-999')};self.assertIn('temperature',warnings);self.assertIn('disk-space',warnings);self.assertIn('undervoltage',warnings);self.assertIn('reboot-required',warnings)
        wid=warnings['temperature']['warning_id'];self.store.acknowledge_warning(wid);self.assertEqual({w['kind']:w for w in self.store.list_warnings('CS-999')}['temperature']['state'],'acknowledged')
        self.store.evaluate_health('CS-999',{'metrics':{'temp_c':50,'disk_pct':20},'health':{}});self.assertNotIn('temperature',{w['kind'] for w in self.store.list_warnings('CS-999')});self.assertIn('temperature',{w['kind'] for w in self.store.list_warnings('CS-999',include_resolved=True)})
    def test_terminal_command_cannot_regress(self):
        cid=self.store.create_command('CS-999','os-update');self.store.transition_command(cid,'failed')
        with self.assertRaises(ValueError):self.store.transition_command(cid,'running')
if __name__=='__main__':unittest.main()
