"""Presentation labels derived from timestamped router evidence; no raw rewrites."""
from copy import deepcopy
from router_client import interpret


def classify(snapshot):
    r=deepcopy(snapshot)
    if r.get('ok'):
        original={k:r.get(k) for k in ('active_path','path_evidence','wan_fields_overlap')}
        r.update(interpret(r.get('wan',{}),r.get('mobile',{}),r.get('radio',{})))
        r['recorded_interpretation']=original
    return r


def apply_labels(session, snapshots):
    s=deepcopy(session)
    for key in ('router_latest','router_last_good'):
        if s.get(key): s[key]=classify(s[key])
    if not s.get('router_capture'): return s
    s['recorded_wan']=s.get('wan');s['recorded_wan_source']=s.get('wan_source')
    latest=s.get('router_latest',{})
    marker=s.get('markers',[])[-1] if s.get('markers') else None
    fresh=latest.get('ok') and s.get('elapsed',0)-latest.get('t',0)<=5
    after_marker=not marker or latest.get('probe_start',latest.get('t',0))>=marker['t']
    if fresh and after_marker:
        s['wan']=latest['active_path'] if latest['active_path']!='Unknown' else 'Unconfirmed'
        s['wan_source']=latest['path_evidence']
    else:
        s['wan']='Unconfirmed'
        s['wan_source']='Waiting for a fresh router reading after the cable marker.' if not after_marker else 'Router status unavailable or stale; last good readings are shown separately.'
    for job in s.get('jobs',[]):
        job['recorded_wan']=job.get('wan')
        candidates=[r for r in snapshots if r.get('at',0)<=job['started']]
        latest_job=max(candidates,key=lambda r:r['at']) if candidates else None
        if latest_job and latest_job.get('ok') and 0<=job['started']-latest_job['at']<=5:
            classified=classify(latest_job)
            label=classified['active_path']
            job['wan']=(label if label!='Unknown' else 'Unconfirmed')+' (at test start)'
            job['wan_source']=classified['path_evidence']
        else:
            job['wan']='Unconfirmed at test start'
            job['wan_source']='No recent successful router snapshot at diagnostic start.'
    return s
