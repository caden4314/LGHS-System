#!/usr/bin/env python3
import json,sqlite3,tempfile,time,unittest
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
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0].lower(),'wal');self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'3');tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name in {'devices','device_tags','fleet_groups','group_members','telemetry_latest','commands','command_events','warnings','warning_events','deployments','deployment_executions','sudo_requests','audit_events','notifications','settings'}:self.assertIn(name,tables)
    def test_v2_schema_upgrades_in_place(self):
        old=self.root/'old.db';db=sqlite3.connect(old)
        try:
            db.executescript("""
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
INSERT INTO metadata VALUES('schema_version','2');
CREATE TABLE devices(device_id TEXT PRIMARY KEY,created_at REAL NOT NULL,updated_at REAL NOT NULL,agent_version TEXT,protocol INTEGER,boot_id TEXT,last_sequence INTEGER,last_seen REAL,transport TEXT,ssh_host TEXT,labels_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE deployments(deployment_id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,target_version TEXT,target_commit TEXT,state TEXT NOT NULL,created_by TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL,policy_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE deployment_executions(deployment_id TEXT NOT NULL REFERENCES deployments(deployment_id) ON DELETE CASCADE,device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,command_id TEXT,phase INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(deployment_id,device_id));
""");db.commit()
        finally:db.close()
        migrated=FleetDB(old);migrated.initialize()
        with migrated.connect() as db:
            device_cols={r['name'] for r in db.execute('PRAGMA table_info(devices)')};execution_cols={r['name'] for r in db.execute('PRAGMA table_info(deployment_executions)')}
            self.assertTrue({'hostname','role','model','ram_mb','serial','current_commit','current_version','desired_commit','health_state'} <= device_cols)
            self.assertTrue({'stage','target_commit','previous_commit','attempt','started_at','completed_at','error_code','error_message'} <= execution_cols)
            self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0],'3')
    def test_inventory_tags_groups_and_deployment_foundation(self):
        current='a'*40;target='b'*40
        row=self.store.update_device_inventory('CS-999',hostname='CS-999',role='student',model='Raspberry Pi 5',ram_mb=8192,serial='10000000abcdef01',current_commit=current,current_version='0.6.0-dev',health_state='healthy')
        self.assertEqual(row['role'],'student');self.assertEqual(row['current_commit'],current);self.assertEqual(row['health_state'],'healthy')
        self.assertEqual(self.store.set_device_tags('CS-999',['room:cs-lab','ring:canary','room:cs-lab']),['ring:canary','room:cs-lab']);self.assertEqual(self.store.list_device_tags('CS-999'),['ring:canary','room:cs-lab'])
        gid=self.store.create_group('Canary',group_id='canary');self.store.add_device_to_group('CS-999',gid);self.assertEqual(self.store.list_groups('CS-999')[0]['group_id'],'canary')
        dep=self.store.create_deployment('0.6 canary',target,target_version='0.6.0-dev',target={'tag':'ring:canary'},strategy={'canary':1},deployment_id='dep-1',now=20);self.store.add_deployment_execution(dep,'CS-999',phase=0,previous_commit=current,now=21)
        execution=self.store.list_deployment_executions(dep)[0];self.assertEqual(execution['target_commit'],target);self.assertEqual(execution['previous_commit'],current);self.assertEqual(execution['state'],'queued')
        with self.assertRaises(ValueError):self.store.create_deployment('moving branch','release-0.6.0-fleet-operations')
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