"""Project structured endpoint health checks into persistent warning lifecycle."""
from __future__ import annotations
from typing import Any,Mapping
from .database import FleetDB

SEVERITIES={'info','warning','critical'}

def evaluate_report(store:FleetDB,device_id:str,payload:Mapping[str,Any])->None:
    report=payload.get('health_report',{}) if isinstance(payload,Mapping) else {}
    if not isinstance(report,Mapping) or report.get('health_version')!=1:return
    seen=set()
    for item in report.get('checks',[]) if isinstance(report.get('checks',[]),list) else []:
        if not isinstance(item,Mapping):continue
        cid=str(item.get('id') or '').strip()
        if not cid or len(cid)>128:continue
        seen.add(cid);state=str(item.get('state') or 'unknown').lower();severity=str(item.get('severity') or 'warning').lower();severity=severity if severity in SEVERITIES else 'warning'
        observed=item.get('observed');expected=item.get('expected');remediation=str(item.get('remediation') or '')
        detail=f"{cid}: observed={observed!r}, expected={expected!r}"
        store.set_warning(device_id,'health.'+cid,active=state=='fail',severity=severity,detail=detail,recommended_action=remediation)
