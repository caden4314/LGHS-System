"""HTTPS audit/event and structured-health helpers for LGHS 0.5."""
from __future__ import annotations
import json,time
from typing import Any,Mapping
from .database import FleetDB
from .protocol import normalize_device_id

ALLOWED_KINDS={'sudo','audit','update','os-update'}
MAX_TEXT=32768
SEVERITIES={'info','warning','critical'}

def record_batches(store:FleetDB,device_id:str,batches:list[Mapping[str,Any]])->dict[str,dict[str,int]]:
    device=normalize_device_id(device_id);acks={}
    if not isinstance(batches,list):return acks
    with store.transaction() as db:
        store.upsert_device(device,db=db)
        for batch in batches[:8]:
            if not isinstance(batch,Mapping):continue
            kind=str(batch.get('kind') or '')
            if kind not in ALLOWED_KINDS:continue
            try:inode=max(0,int(batch.get('inode') or 0));offset=max(0,int(batch.get('offset') or 0));next_offset=max(offset,int(batch.get('next_offset') or offset))
            except Exception:continue
            text=str(batch.get('text') or '')[:MAX_TEXT]
            if text:
                exists=db.execute('SELECT 1 FROM audit_events WHERE device_id=? AND kind=? AND sequence=? LIMIT 1',(device,kind,offset)).fetchone()
                if not exists:
                    detail={'inode':inode,'offset':offset,'next_offset':next_offset,'text':text}
                    db.execute('INSERT INTO audit_events(device_id,kind,severity,created_at,sequence,detail_json) VALUES(?,?,?,?,?,?)',(device,kind,'info',time.time(),offset,json.dumps(detail,separators=(',',':'))))
            acks[kind]={'inode':inode,'next_offset':next_offset}
    return acks

def evaluate_report(store:FleetDB,device_id:str,payload:Mapping[str,Any])->None:
    report=payload.get('health_report',{}) if isinstance(payload,Mapping) else {}
    if not isinstance(report,Mapping) or report.get('health_version')!=1:return
    for item in report.get('checks',[]) if isinstance(report.get('checks',[]),list) else []:
        if not isinstance(item,Mapping):continue
        cid=str(item.get('id') or '').strip()
        if not cid or len(cid)>128:continue
        state=str(item.get('state') or 'unknown').lower();severity=str(item.get('severity') or 'warning').lower();severity=severity if severity in SEVERITIES else 'warning'
        observed=item.get('observed');expected=item.get('expected');remediation=str(item.get('remediation') or '')
        detail=f"{cid}: observed={observed!r}, expected={expected!r}"
        store.set_warning(device_id,'health.'+cid,active=state=='fail',severity=severity,detail=detail,recommended_action=remediation)
