"""Transactional SQLite state store for LGHS 0.5."""
from __future__ import annotations
import json, sqlite3, time, uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping
from .protocol import ALLOWED_COMMANDS, TERMINAL_COMMAND_STATES, normalize_command_state, normalize_device_id, state_can_advance

DEFAULT_DB = Path('/var/lib/lghs/fleet.db')
SCHEMA_VERSION = 2
OPEN_STATES = {'queued','delivered','received','accepted','running'}
SCHEMA = r'''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS devices(device_id TEXT PRIMARY KEY,created_at REAL NOT NULL,updated_at REAL NOT NULL,agent_version TEXT,protocol INTEGER,boot_id TEXT,last_sequence INTEGER,last_seen REAL,transport TEXT,ssh_host TEXT,labels_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS telemetry_latest(device_id TEXT PRIMARY KEY REFERENCES devices(device_id) ON DELETE CASCADE,received_at REAL NOT NULL,sent_at REAL,boot_id TEXT,sequence INTEGER,payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS commands(command_id TEXT PRIMARY KEY,device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,action TEXT NOT NULL,state TEXT NOT NULL,stage TEXT NOT NULL DEFAULT '',message TEXT NOT NULL DEFAULT '',progress REAL,created_at REAL NOT NULL,updated_at REAL NOT NULL,deadline_at REAL,delivered_at REAL,received_at REAL,accepted_at REAL,started_at REAL,completed_at REAL,last_delivery_at REAL,deliveries INTEGER NOT NULL DEFAULT 0,payload_json TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS idx_commands_device_created ON commands(device_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_commands_state ON commands(state,updated_at);
CREATE TABLE IF NOT EXISTS command_events(id INTEGER PRIMARY KEY AUTOINCREMENT,command_id TEXT NOT NULL REFERENCES commands(command_id) ON DELETE CASCADE,state TEXT NOT NULL,stage TEXT NOT NULL DEFAULT '',message TEXT NOT NULL DEFAULT '',progress REAL,created_at REAL NOT NULL,detail_json TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS idx_command_events_command ON command_events(command_id,id);
CREATE TABLE IF NOT EXISTS warnings(warning_id TEXT PRIMARY KEY,device_id TEXT REFERENCES devices(device_id) ON DELETE CASCADE,kind TEXT NOT NULL,severity TEXT NOT NULL,state TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',recommended_action TEXT NOT NULL DEFAULT '',first_seen REAL NOT NULL,last_seen REAL NOT NULL,acknowledged_at REAL,resolved_at REAL);
CREATE TABLE IF NOT EXISTS warning_events(id INTEGER PRIMARY KEY AUTOINCREMENT,warning_id TEXT NOT NULL REFERENCES warnings(warning_id) ON DELETE CASCADE,state TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS deployments(deployment_id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,target_version TEXT,target_commit TEXT,state TEXT NOT NULL,created_by TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL,policy_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS deployment_executions(deployment_id TEXT NOT NULL REFERENCES deployments(deployment_id) ON DELETE CASCADE,device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,command_id TEXT REFERENCES commands(command_id) ON DELETE SET NULL,phase INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(deployment_id,device_id));
CREATE TABLE IF NOT EXISTS sudo_requests(request_id TEXT PRIMARY KEY,device_id TEXT REFERENCES devices(device_id) ON DELETE CASCADE,state TEXT NOT NULL,command TEXT NOT NULL,requested_at REAL NOT NULL,updated_at REAL NOT NULL,expires_at REAL,detail_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY AUTOINCREMENT,device_id TEXT REFERENCES devices(device_id) ON DELETE SET NULL,kind TEXT NOT NULL,severity TEXT NOT NULL DEFAULT 'info',created_at REAL NOT NULL,sequence INTEGER,detail_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS notifications(notification_id TEXT PRIMARY KEY,device_id TEXT REFERENCES devices(device_id) ON DELETE SET NULL,kind TEXT NOT NULL,severity TEXT NOT NULL,state TEXT NOT NULL,message TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value_json TEXT NOT NULL,updated_at REAL NOT NULL);
'''

def _json(v: Any)->str: return json.dumps(v,sort_keys=True,separators=(',',':'))
def _load(path: Path, default: Any)->Any:
    try: return json.loads(path.read_text(encoding='utf-8'))
    except Exception: return default

class FleetDB:
    def __init__(self,path: str|Path=DEFAULT_DB): self.path=Path(path)
    def connect(self)->sqlite3.Connection:
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.path,timeout=15,isolation_level=None)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON'); db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA synchronous=NORMAL'); db.execute('PRAGMA busy_timeout=15000')
        return db
    def initialize(self)->None:
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.execute("INSERT INTO metadata(key,value) VALUES('schema_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(SCHEMA_VERSION),))
    @contextmanager
    def transaction(self,immediate: bool=True)->Iterator[sqlite3.Connection]:
        db=self.connect()
        try:
            db.execute('BEGIN IMMEDIATE' if immediate else 'BEGIN'); yield db; db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK'); raise
        finally: db.close()
    def upsert_device(self,device_id:str,*,agent_version=None,protocol=None,boot_id=None,sequence=None,last_seen=None,transport=None,ssh_host=None,labels=None,db=None)->str:
        d=normalize_device_id(device_id); now=time.time(); labels_json=_json(dict(labels or {}))
        sql='''INSERT INTO devices(device_id,created_at,updated_at,agent_version,protocol,boot_id,last_sequence,last_seen,transport,ssh_host,labels_json) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET updated_at=excluded.updated_at,agent_version=COALESCE(excluded.agent_version,devices.agent_version),protocol=COALESCE(excluded.protocol,devices.protocol),boot_id=COALESCE(excluded.boot_id,devices.boot_id),last_sequence=COALESCE(excluded.last_sequence,devices.last_sequence),last_seen=COALESCE(excluded.last_seen,devices.last_seen),transport=COALESCE(excluded.transport,devices.transport),ssh_host=COALESCE(excluded.ssh_host,devices.ssh_host),labels_json=CASE WHEN excluded.labels_json='{}' THEN devices.labels_json ELSE excluded.labels_json END'''
        vals=(d,now,now,agent_version,protocol,boot_id,sequence,last_seen,transport,ssh_host,labels_json)
        if db is not None: db.execute(sql,vals)
        else:
            with self.transaction() as tx: tx.execute(sql,vals)
        return d
    def record_telemetry(self,device_id:str,payload:Mapping[str,Any],*,received_at=None,sent_at=None,agent_version=None,protocol=None,boot_id=None,sequence=None)->None:
        d=normalize_device_id(device_id); received=time.time() if received_at is None else float(received_at)
        with self.transaction() as db:
            old=db.execute('SELECT boot_id,last_sequence FROM devices WHERE device_id=?',(d,)).fetchone()
            if old and boot_id and old['boot_id']==boot_id and sequence is not None and old['last_sequence'] is not None and int(sequence)<=int(old['last_sequence']): raise ValueError('out-of-order telemetry sequence')
            self.upsert_device(d,agent_version=agent_version,protocol=protocol,boot_id=boot_id,sequence=sequence,last_seen=received,db=db)
            db.execute('''INSERT INTO telemetry_latest(device_id,received_at,sent_at,boot_id,sequence,payload_json) VALUES(?,?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET received_at=excluded.received_at,sent_at=excluded.sent_at,boot_id=excluded.boot_id,sequence=excluded.sequence,payload_json=excluded.payload_json''',(d,received,sent_at,boot_id,sequence,_json(dict(payload))))
    def create_command(self,device_id:str,action:str,*,payload=None,deadline_at=None,command_id=None,now=None,dedupe=True)->str:
        d=normalize_device_id(device_id)
        if action not in ALLOWED_COMMANDS: raise ValueError(f'unsupported command: {action}')
        ts=time.time() if now is None else float(now); cid=command_id or uuid.uuid4().hex
        with self.transaction() as db:
            self.upsert_device(d,db=db)
            if dedupe:
                q=','.join('?' for _ in OPEN_STATES)
                row=db.execute(f'SELECT command_id FROM commands WHERE device_id=? AND action=? AND state IN ({q}) ORDER BY created_at DESC LIMIT 1',(d,action,*sorted(OPEN_STATES))).fetchone()
                if row: return str(row['command_id'])
            db.execute('''INSERT INTO commands(command_id,device_id,action,state,stage,message,progress,created_at,updated_at,deadline_at,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(cid,d,action,'queued','Waiting for device','Queued on controller',0,ts,ts,deadline_at,_json(dict(payload or {}))))
            self._event(db,cid,'queued','Waiting for device','Queued on controller',0,ts,{})
        return cid
    def _event(self,db,cid,state,stage,message,progress,ts,detail): db.execute('INSERT INTO command_events(command_id,state,stage,message,progress,created_at,detail_json) VALUES(?,?,?,?,?,?,?)',(cid,state,stage,message,progress,ts,_json(detail)))
    def transition_command(self,cid:str,state:str,*,stage=None,message=None,progress=None,now=None,detail=None)->dict[str,Any]:
        ns=normalize_command_state(state); ts=time.time() if now is None else float(now)
        with self.transaction() as db:
            r=db.execute('SELECT * FROM commands WHERE command_id=?',(cid,)).fetchone()
            if not r: raise KeyError(cid)
            if not state_can_advance(r['state'],ns): raise ValueError(f"command state regression: {r['state']} -> {ns}")
            vals=dict(r); st=vals['stage'] if stage is None else str(stage); msg=vals['message'] if message is None else str(message); prog=vals['progress'] if progress is None else progress
            delivered=vals['delivered_at']; received=vals['received_at']; accepted=vals['accepted_at']; started=vals['started_at']; completed=vals['completed_at']
            if ns=='delivered' and delivered is None: delivered=ts
            if ns=='received' and received is None: received=ts
            if ns=='accepted' and accepted is None: accepted=ts
            if ns=='running' and started is None: started=ts
            if ns in TERMINAL_COMMAND_STATES and completed is None: completed=ts
            db.execute('UPDATE commands SET state=?,stage=?,message=?,progress=?,updated_at=?,delivered_at=?,received_at=?,accepted_at=?,started_at=?,completed_at=? WHERE command_id=?',(ns,st,msg,prog,ts,delivered,received,accepted,started,completed,cid))
            self._event(db,cid,ns,st,msg,prog,ts,dict(detail or {}))
            return dict(db.execute('SELECT * FROM commands WHERE command_id=?',(cid,)).fetchone())
    def reconcile_reported_commands(self,device_id:str,reported:list[Mapping[str,Any]])->None:
        d=normalize_device_id(device_id)
        for item in reported if isinstance(reported,list) else []:
            cid=str(item.get('id') or '')
            if not cid: continue
            with self.connect() as db: row=db.execute('SELECT device_id,state FROM commands WHERE command_id=?',(cid,)).fetchone()
            if not row or row['device_id']!=d: continue
            try:
                self.transition_command(cid,str(item.get('state') or 'accepted'),stage=item.get('stage'),message=item.get('message'),progress=item.get('progress'),now=float(item.get('updated_at') or time.time()),detail={'update_state':item.get('update_state')})
            except ValueError: pass
    def commands_for_delivery(self,device_id:str,*,now=None,ttl=86400,limit=16)->list[dict[str,Any]]:
        d=normalize_device_id(device_id); ts=time.time() if now is None else float(now); out=[]
        with self.transaction() as db:
            rows=db.execute('SELECT * FROM commands WHERE device_id=? ORDER BY created_at',(d,)).fetchall()
            for r in rows:
                state=normalize_command_state(r['state']); deadline=r['deadline_at'] or (r['created_at']+ttl)
                if state not in TERMINAL_COMMAND_STATES and ts>deadline:
                    db.execute("UPDATE commands SET state='timed_out',stage='Command timed out',message='Device did not accept command before deadline',updated_at=?,completed_at=? WHERE command_id=?",(ts,ts,r['command_id']))
                    self._event(db,r['command_id'],'timed_out','Command timed out','Device did not accept command before deadline',r['progress'],ts,{})
                    continue
                if state not in {'queued','delivered','received'}: continue
                if state=='queued':
                    db.execute("UPDATE commands SET state='delivered',delivered_at=COALESCE(delivered_at,?),updated_at=? WHERE command_id=?",(ts,ts,r['command_id']))
                    self._event(db,r['command_id'],'delivered','Delivered to device','Waiting for device acceptance',0,ts,{})
                db.execute('UPDATE commands SET last_delivery_at=?,deliveries=deliveries+1 WHERE command_id=?',(ts,r['command_id']))
                payload=json.loads(r['payload_json'] or '{}')
                out.append({'id':r['command_id'],'action':r['action'],'created_at':r['created_at'],'payload':payload})
                if len(out)>=limit: break
        return out
    def get_command(self,cid:str):
        with self.connect() as db:
            r=db.execute('SELECT * FROM commands WHERE command_id=?',(cid,)).fetchone(); return dict(r) if r else None
    def list_commands(self,device_id=None,limit=64):
        with self.connect() as db:
            if device_id: rows=db.execute('SELECT * FROM commands WHERE device_id=? ORDER BY created_at DESC LIMIT ?',(normalize_device_id(device_id),limit)).fetchall()
            else: rows=db.execute('SELECT * FROM commands ORDER BY created_at DESC LIMIT ?',(limit,)).fetchall()
            return [dict(x) for x in rows]
    def latest_telemetry(self,device_id:str):
        with self.connect() as db:
            r=db.execute('SELECT * FROM telemetry_latest WHERE device_id=?',(normalize_device_id(device_id),)).fetchone()
            if not r:return None
            x=dict(r); x['payload']=json.loads(x.pop('payload_json')); return x
    def migrate_legacy(self,*,registry=Path('/etc/lghs/fleet.json'),cache=Path('/var/lib/lghs/fleet-cache.json'),commands=Path('/var/lib/lghs/fleet-commands.json'))->dict[str,int]:
        counts={'devices':0,'telemetry':0,'commands':0}; self.initialize()
        reg=_load(registry,{})
        for did,meta in (reg.get('devices',{}) if isinstance(reg,dict) else {}).items():
            try: self.upsert_device(did,transport=(meta or {}).get('transport'),ssh_host=(meta or {}).get('ssh_host')); counts['devices']+=1
            except Exception: pass
        c=_load(cache,{})
        for did,p in (c.get('devices',{}) if isinstance(c,dict) else {}).items():
            try: self.record_telemetry(did,p,received_at=p.get('received_at') or time.time()); counts['telemetry']+=1
            except Exception: pass
        q=_load(commands,{})
        for did,rows in (q.get('devices',{}) if isinstance(q,dict) else {}).items():
            for r in rows if isinstance(rows,list) else []:
                try:
                    cid=str(r.get('id') or uuid.uuid4().hex); state=normalize_command_state(r.get('state') or 'queued')
                    if self.get_command(cid): continue
                    self.create_command(did,str(r.get('action')),command_id=cid,now=float(r.get('created_at') or time.time()),dedupe=False)
                    if state!='queued': self.transition_command(cid,state,stage=r.get('stage'),message=r.get('message'),progress=r.get('progress'),now=float(r.get('updated_at') or time.time()))
                    counts['commands']+=1
                except Exception: pass
        return counts
    def export_legacy_commands(self,path=Path('/var/lib/lghs/fleet-commands.json'))->None:
        data={'version':2,'devices':{},'updated_at':time.time()}
        for row in self.list_commands(limit=5000):
            r=dict(row); r['id']=r.pop('command_id'); r['device']=r.pop('device_id'); r.pop('payload_json',None); data['devices'].setdefault(r['device'],[]).append(r)
        tmp=path.with_suffix('.tmp'); tmp.write_text(_json(data)+'\n',encoding='utf-8'); tmp.chmod(0o600); tmp.replace(path)
