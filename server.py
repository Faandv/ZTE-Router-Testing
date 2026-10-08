#!/usr/bin/env python3
"""Router Lab: loopback-only network diagnostics for macOS."""
import concurrent.futures as cf
import csv
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import statistics
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get('ROUTER_LAB_PORT', '8765'))
DATA = Path(os.environ.get('ROUTER_LAB_DATA', ROOT / 'data'))
DATA.mkdir(exist_ok=True, parents=True)
LOCK = threading.RLock()
DB = sqlite3.connect(DATA / 'lab.sqlite3', check_same_thread=False)
DB.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, doc TEXT NOT NULL)')
DB.execute('CREATE TABLE IF NOT EXISTS samples (session TEXT, seq INTEGER, doc TEXT, PRIMARY KEY(session,seq))')
DB.execute('CREATE TABLE IF NOT EXISTS router_samples (session TEXT, seq INTEGER, doc TEXT, PRIMARY KEY(session,seq))')
DB.commit()
TOKEN = secrets.token_urlsafe(32)
ACTIVE = None
STOP = threading.Event()
JOB = None
TOOLS = {n: shutil.which(n, path='/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin') for n in ['ping','mtr','curl','dig','networkQuality','networksetup','route','ifconfig','ipconfig']}
POOL = cf.ThreadPoolExecutor(max_workers=12)


def run(args, timeout=10):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env={**os.environ, 'LC_ALL':'C'}, start_new_session=True)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, '', 'Timed out'
    except OSError as e:
        return 127, '', str(e)


def save(s):
    DB.execute('INSERT OR REPLACE INTO sessions VALUES (?,?)', (s['id'], json.dumps(s)))
    DB.commit()


def get_session(sid):
    row = DB.execute('SELECT doc FROM sessions WHERE id=?', (sid,)).fetchone()
    if not row:
        raise ValueError('Session not found')
    return json.loads(row[0])


def samples(sid, limit=None):
    if limit:
        rows = DB.execute('SELECT doc FROM (SELECT seq,doc FROM samples WHERE session=? ORDER BY seq DESC LIMIT ?) ORDER BY seq', (sid,limit))
    else:
        rows = DB.execute('SELECT doc FROM samples WHERE session=? ORDER BY seq', (sid,))
    return [json.loads(r[0]) for r in rows]


def event(s, kind, label, t=None, **extra):
    s['events'].append({'kind':kind,'label':label,'t':elapsed(s) if t is None else t,'at':time.time(), **extra})


def elapsed(s):
    return round(time.monotonic() - s['_mono'], 3)


def network():
    _, raw, err = run([TOOLS['networksetup'], '-listallhardwareports'])
    _, route, _ = run([TOOLS['route'], '-n','get','default'])
    default = re.search(r'interface:\s*(\S+)',route)
    gateway = re.search(r'gateway:\s*(\S+)',route)
    interfaces=[]
    for name, dev in re.findall(r'Hardware Port: ([^\n]+)\nDevice: (\S+)',raw):
        _, info, _ = run([TOOLS['ifconfig'],dev])
        ip = re.search(r'\binet (\d+\.\d+\.\d+\.\d+)',info)
        if 'Wi-Fi' not in name and 'Ethernet' not in name and 'LAN' not in name:
            continue
        _, gw, _ = run([TOOLS['ipconfig'],'getoption',dev,'router'])
        gw = gw.strip().splitlines()[0] if gw.strip() else ''
        interfaces.append({'name':name,'device':dev,'kind':'Wi-Fi' if 'Wi-Fi' in name else 'Ethernet','ip':ip[1] if ip else None,'active':'status: active' in info, 'gateway':gw or (gateway[1] if gateway and default and default[1]==dev else '')})
    return {'interfaces':interfaces,'default':default[1] if default else None,'gateway':gateway[1] if gateway else None,'error':err.strip() or None}


def ping(host, interface):
    start=time.monotonic()
    code,out,err=run([TOOLS['ping'],'-n','-c','1','-W','650','-b',interface,host],1.25)
    match=re.search(r'time[=<]([\d.]+) ms',out)
    return {'ok':bool(match) and code==0,'ms':float(match[1]) if match else None,'duration':round(time.monotonic()-start,3), 'error':err.strip()[:180] or None}


def web_probe(interface):
    code,out,err=run([TOOLS['curl'],'--noproxy','*','-4','--interface',interface,'--max-time','1.4','--connect-timeout','1','-sS','-o','/dev/null','-w','%{http_code} %{time_total}','https://example.com/'],2)
    parts=out.strip().split()
    return {'ok':code==0 and bool(parts) and parts[0]=='200', 'ms':round(float(parts[1])*1000,2) if len(parts)==2 else None, 'error':err.strip()[:180] or None}


def dns_probe(ip):
    code,out,err=run([TOOLS['dig'],'-b',ip,'+time=1','+tries=1','+stats','example.com','A'],2)
    ok=code==0 and 'status: NOERROR' in out and bool(re.search(r'ANSWER: [1-9]',out))
    match=re.search(r'Query time: (\d+) msec',out)
    return {'ok':ok,'ms':int(match[1]) if match else None,'error':err.strip()[:180] or None}


def identity(interface):
    code,out,err=run([TOOLS['curl'],'--noproxy','*','-4','--interface',interface,'--max-time','10','-sS','https://ipwho.is/'],12)
    try:
        d=json.loads(out)
        if code or not d.get('success'):
            raise ValueError(d.get('message','IP lookup failed'))
        return {'ip':d['ip'],'isp':d.get('connection',{}).get('isp'),'asn':d.get('connection',{}).get('asn'),'at':time.time()}
    except (ValueError,KeyError):
        return {'error':err.strip() or 'Public IP lookup unavailable', 'at':time.time()}


def process_sample(s,p):
    """Timing uses monotonic probe completion times; never infers physical unplug time."""
    s['count']+=1
    stats=s['stats']
    for key in ['cloudflare','google']:
        stats['sent']+=1
        if not p[key]['ok']: stats['lost']+=1
        else:
            v=p[key]['ms']; stats['sum']+=v; stats['received']+=1
            stats['min']=min(stats['min'],v) if stats['min'] is not None else v
            stats['max']=max(stats['max'],v) if stats['max'] is not None else v
            if stats['previous'].get(key) is not None: stats['jitter_sum']+=abs(v-stats['previous'][key]); stats['jitter_n']+=1
            stats['previous'][key]=v
    if p['loaded']:
        s.pop('last_sample_t',None)
        s.pop('last_sample_wall',None)
        return
    usable=p['web']['ok'] and (p['cloudflare']['ok'] or p['google']['ok'])
    s['stable']=s.get('stable',0)+1 if usable else 0
    previous=s.get('last_sample_t')
    if previous is not None:
        s['max_gap']=max(s.get('max_gap',0),p['t']-previous)
    wall_gap=p['at']-s.get('last_sample_wall',p['at'])
    mono_gap=p['t']-previous if previous is not None else 0
    if previous is not None and (mono_gap>5 or abs(wall_gap-mono_gap)>3):
        event(s,'gap','Monitoring gap detected; transition timing may be unreliable',p['t'])
        if s.get('transition'): s['transition']['timing_gap']=True
        if s.get('markers') and not s['markers'][-1].get('closed'): s['markers'][-1]['timing_unreliable']=True
    s['last_sample_wall']=p['at']
    s['last_sample_t']=p['t']
    if usable:
        s['last_good']=p['t']
        if s.get('outage') and s['stable']>=3:
            o=s.pop('outage')
            o['recovered']=p['t']; o['first_recovered']=s['candidate_recovery']; o['duration']=round(o['first_recovered']-o['first_failure'],3)
            o['upper_duration']=round(p['t']-o['last_good'],3) if o['last_good'] is not None else None
            s['outages'].append(o)
            event(s,'recovery','Stable internet recovery',p['t'],outage=o)
        if s['stable']==1:
            s['candidate_recovery']=p['t']
    else:
        if not s.get('outage'):
            s['outage']={'first_failure':p['t'],'last_good':s.get('last_good'),'phase':s['phase']}
            event(s,'outage','Internet checks stopped passing',p['t'])
    transition=s.get('transition')
    if transition and not transition.get('complete') and p.get('probe_start',p['t']) >= transition['marker']:
        if not usable: transition['saw_failure']=True
        delta=p['t']-transition['marker']
        if delta>=60 and not transition.get('deadline_logged'):
            event(s,'deadline','60-second target reached; WAN confirmation still required' if s['stable']>=3 else '60-second target reached without stable recovery',p['t'])
            transition['deadline_logged']=True
        # A healthy probe stream alone is NOT evidence that WAN failover happened.
        if transition.get('saw_failure') and s['stable']>=3 and transition.get('recovered') is None:
            transition['recovered']=p['t']
            transition['first_recovered']=s['candidate_recovery']
            transition['marker_to_recovery']=round(p['t']-transition['marker'],3)
            event(s,'transition_recovery','Connectivity restored; confirm the active WAN',p['t'])


def monitor(sid):
    seq=0
    while not STOP.is_set():
        tick=time.monotonic()
        with LOCK:
            s=get_session(sid)
            if s['status']!='running': break
            interface=s['interface']; gateway=s['gateway']; ip=s['local_ip']
            loaded=bool(JOB and JOB.get('kind')=='speed' and JOB['status']=='running')
        futures={k:POOL.submit(ping,h,interface) for k,h in [('router',gateway),('cloudflare','1.1.1.1'),('google','8.8.8.8')]}
        futures['web']=POOL.submit(web_probe,interface)
        futures['dns']=POOL.submit(dns_probe,ip)
        try:
            results={k:f.result() for k,f in futures.items()}
            with LOCK:
                s=get_session(sid)
                if s['status']!='running': break
                seq+=1
                p={'seq':seq,'probe_start':round(tick-s['_mono'],3),'t':elapsed(s),'at':time.time(),'phase':s['phase'],'loaded':loaded or bool(JOB and JOB.get('kind')=='speed' and JOB['status']=='running'),**results}
                process_sample(s,p)
                record_marker_progress(s,p)
                DB.execute('INSERT INTO samples VALUES (?,?,?)',(sid,seq,json.dumps(p)))
                save(s)
        except Exception as e:
            with LOCK:
                s=get_session(sid); event(s,'error',f'Monitor error: {e}'); save(s)
        STOP.wait(max(0,1-(time.monotonic()-tick)))


def router_samples(sid):
    return [json.loads(r[0]) for r in DB.execute('SELECT doc FROM router_samples WHERE session=? ORDER BY seq',(sid,))]


def router_credentials():
    try: return json.loads((DATA/'router-credentials.json').read_text())
    except (OSError,ValueError): return {}


def record_marker_progress(s,p):
    if not s.get('markers'): return
    marker=s['markers'][-1]
    if marker.get('closed') or p.get('probe_start',p['t'])<marker['t']: return
    if p['loaded']:
        marker['timing_unreliable']=True
        return
    if marker.get('last_sample') is not None and p['t']-marker['last_sample']>5: marker['timing_unreliable']=True
    marker['last_sample']=p['t']
    if not(p['web']['ok'] and (p['cloudflare']['ok'] or p['google']['ok'])):
        marker.setdefault('first_failure',p['t'])
    elif 'first_failure' in marker and s.get('stable',0)>=3 and 'recovered' not in marker:
        marker['recovered']=p['t'];marker['marker_to_recovery']=round(p['t']-marker['t'],3)
        marker['status']='recovered'
        event(s,'marker_recovery',f"Stable internet after {marker['label']}: {marker['marker_to_recovery']:.3f}s from manual marker",p['t'])


def process_router_snapshot(s,r):
    old=s.get('router_latest')
    s['router_count']=s.get('router_count',0)+1
    s['router_latest']=r
    if not r['ok']:
        s['router_failures']=s.get('router_failures',0)+1
        if old is None or old.get('ok'):event(s,'router_unavailable','Router status API unavailable: '+r.get('error','Unknown error'),r['t'])
        return
    s['router_successes']=s.get('router_successes',0)+1
    if old is None or not old.get('ok'):
        event(s,'router_available','Router status API responding; '+r['active_path'],r['t'])
    if not s.get('firmware'):s['firmware']=r.get('device',{}).get('wa_inner_version') or ''
    previous=s.get('router_last_good')
    labels={'opms_wan_mode':'operating mode','opms_wan_auto_mode':'Auto submode','current_wan_interface':'active interface','current_wan_status':'internet status','mwan_wanlan1_link_state':'WAN link field','mwan_wanlan1_link_mode':'WAN address mode','mwan_wanlan1_status':'WAN connection field','mwan_wanlan1_wan_ipaddr':'WAN IP field'}
    fields=['opms_wan_mode','opms_wan_auto_mode','current_wan_interface','current_wan_status','mwan_wanlan1_link_state','mwan_wanlan1_link_mode','mwan_wanlan1_status','mwan_wanlan1_wan_ipaddr']
    if previous:
        for key in fields:
            before=previous['wan'].get(key);after=r['wan'].get(key)
            if before!=after:
                s['router_changes']=s.get('router_changes',0)+1
                event(s,'router_change',f"Router {labels[key]}: {before or 'empty'} → {after or 'empty'}",r['t'],field=key,before=before,after=after,observed_between=[previous['t'],r['t']])
        if previous.get('active_path')!=r['active_path']:
            event(s,'path_change',f"Router-reported path: {previous.get('active_path')} → {r['active_path']}",r['t'])
        before=previous.get('mobile',{}).get('connect_status');after=r.get('mobile',{}).get('connect_status')
        if before!=after:event(s,'mobile_change',f'Mobile connection: {before} → {after}',r['t'])
    s['router_last_good']=r


def router_monitor(sid,credential):
    from router_client import RouterClient
    with LOCK:s=get_session(sid)
    client=RouterClient(s['gateway'],s['local_ip'],credential['password_hash'])
    seq=0
    while True:
        tick=time.monotonic()
        with LOCK:
            s=get_session(sid)
            if s['status']!='running':return
            started=elapsed(s)
        r=client.snapshot()
        with LOCK:
            s=get_session(sid)
            if s['status']!='running':return
            seq+=1;r.update({'seq':seq,'probe_start':started,'t':elapsed(s),'phase':s['phase']})
            process_router_snapshot(s,r)
            DB.execute('INSERT INTO router_samples VALUES (?,?,?)',(sid,seq,json.dumps(r)));save(s)
        time.sleep(max(0,1-(time.monotonic()-tick)))


def start_session(body):
    global ACTIVE
    with LOCK:
        if ACTIVE: raise ValueError('Finish the active session first')
        if JOB and JOB['status']=='running': raise ValueError('Wait for the current diagnostic to finish')
        n=network()
        interface=next((i for i in n['interfaces'] if i['device']==body.get('interface')),None)
        if not interface or not interface['ip'] or not interface['active']: raise ValueError('Choose a connected interface with an IPv4 address')
        gateway=body.get('gateway') or interface['gateway']
        try: ipaddress.IPv4Address(gateway)
        except ValueError: raise ValueError('Enter the router LAN IPv4 address')
        mode=body.get('mode','baseline')
        if mode not in ['baseline','guided','recording']: raise ValueError('Invalid session mode')
        wan=body.get('wan','5G')
        if wan not in ['5G','Fibre','Unknown']: raise ValueError('Invalid WAN')
        if mode=='guided' and wan!='Fibre': raise ValueError('Guided failover starts on confirmed fibre. Use a 5G baseline now.')
        capture=mode=='recording' and body.get('router_capture',True) not in [False,'off']
        credential=router_credentials()
        password=body.get('router_password','')
        if password:
            from router_client import digest
            credential={'host':gateway,'password_hash':digest(password)}
        if capture and (credential.get('host')!=gateway or not credential.get('password_hash')):raise ValueError('Enter the router password to enable status recording for this address')
        sid=uuid.uuid4().hex[:12]
        s={'id':sid,'name':str(body.get('name') or ('Failover test' if mode=='guided' else f'{wan} baseline'))[:120], 'router':'ZTE G5TS Pro','firmware':str(body.get('firmware',''))[:120],'notes':str(body.get('notes',''))[:4000], 'mode':mode,'wan':wan,'wan_source':'manually confirmed' if wan!='Unknown' else 'unconfirmed','interface':interface['device'],'connection':interface['kind'],'gateway':gateway,'local_ip':interface['ip'],'default_route':n['default'],'vpn_detected':bool(n['default'] and n['default'].startswith('utun')),'status':'running','phase':'fibre_baseline' if mode=='guided' else 'baseline','started':time.time(),'_mono':time.monotonic(),'count':0,'events':[],'outages':[],'transitions':[],'jobs':[],'identities':[],'stable':0,'max_gap':0,'stats':{'sent':0,'lost':0,'sum':0,'received':0,'min':None,'max':None,'previous':{},'jitter_sum':0,'jitter_n':0}}
        s.update({'router_capture':capture,'markers':[],'router_count':0,'router_successes':0,'router_failures':0,'router_changes':0})
        if mode=='recording': s['phase']='initial'; s['name']=str(body.get('name') or 'Auto mode — DHCP recording')[:120]
        event(s,'start',f'{interface["kind"]} session started; {wan} manually selected',0)
        save(s); ACTIVE=sid; STOP.clear()
        threading.Thread(target=monitor,args=(sid,),daemon=True).start()
        if capture:threading.Thread(target=router_monitor,args=(sid,credential),daemon=True).start()
        return s


def do_action(body):
    received_at=time.monotonic()
    received_wall=time.time()
    global ACTIVE
    with LOCK:
        if not ACTIVE: raise ValueError('Start a session first')
        s=get_session(ACTIVE); action=body.get('action')
        if action in ['wan_plugged','wan_unplugged']:
            if s['mode']!='recording':raise ValueError('Cable markers are available in recording mode')
            if body.get('session_id') and body['session_id']!=s['id']:raise ValueError('This recording has ended; refresh before adding a marker')
            request_id=body.get('request_id')
            if request_id is not None and (not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',request_id)):raise ValueError('Invalid marker request identifier')
            if request_id:
                prior=next((m for m in s['markers'] if m.get('request_id')==request_id),None)
                if prior:
                    if prior['action']!=action:raise ValueError('Marker request identifier was already used for another action')
                    return {**s,'marker_ack':prior,'marker_duplicate':True}
            previous=s['markers'][-1] if s['markers'] else None
            if previous and previous['action']==action and 0<=received_at-s['_mono']-previous['t']<2:
                return {**s,'marker_ack':previous,'marker_duplicate':True}
            if previous:previous['closed']=True
            label='WAN plugged in' if action=='wan_plugged' else 'WAN unplugged'
            marker={'id':len(s['markers'])+1,'action':action,'label':label,'at':received_wall,'request_id':request_id,'t':round(received_at-s['_mono'],3),'status':'watching','timing_unreliable':bool(JOB and JOB['status']=='running' and JOB['kind']=='speed')}
            s['markers'].append(marker);s['phase']=f'{action}_{marker["id"]}'
            # A manual cable marker does not establish which WAN is carrying traffic.
            s['wan']='Unknown';s['wan_source']='cable marker; inspect router status'
            event(s,'cable_marker',label+' — manual marker',marker['t'],marker_id=marker['id']);save(s);return {**s,'marker_ack':marker,'marker_duplicate':False}
        if JOB and JOB['status']=='running' and action!='note': raise ValueError('Wait for the diagnostic to finish before changing test phase')
        if action in ['unplug','reconnect']:
            expected='fibre_baseline' if action=='unplug' else '5g_baseline'
            if s['mode']!='guided' or s['phase']!=expected: raise ValueError('This action is not available in this phase')
            if s['stable']<3: raise ValueError('Wait for three consecutive healthy monitoring samples')
            s['phase']='failover' if action=='unplug' else 'failback'
            s['transition']={'kind':s['phase'],'marker':elapsed(s),'complete':False,'saw_failure':False}
            event(s,'marker','Manual WAN unplug marker' if action=='unplug' else 'Manual fibre reconnect marker',s['transition']['marker'])
            s['wan']='Unknown'; s['wan_source']='transition in progress'; s['stable']=0
        elif action in ['confirm_5g','confirm_fibre']:
            expected='failover' if action=='confirm_5g' else 'failback'
            if s['phase']!=expected or s['stable']<3: raise ValueError('Confirmation requires the matching phase and stable internet')
            t=s['transition']; t['complete']=True; t['confirmed_at']=elapsed(s); t['confirmation']='manual'
            if t.get('timing_gap'):
                t['verdict']='inconclusive'; t['reason']='A monitoring gap occurred during the transition; timing is unreliable.'
            elif t.get('recovered') is None:
                t['verdict']='inconclusive'; t['reason']='No interruption was observed; physical switch timing is unknown.'
            else:
                t['verdict']='pass' if t['marker_to_recovery']<60 else 'fail'
                t['reason']='Manual-marker to stable connectivity recovery; physical unplug timing is unverified.'
            s['transitions'].append(t); s.pop('transition')
            s['wan']='5G' if action=='confirm_5g' else 'Fibre'; s['wan_source']='manually confirmed'
            s['phase']='5g_baseline' if action=='confirm_5g' else 'restored'
            event(s,'wan',f'{s["wan"]} manually confirmed')
        elif action=='finish':
            for marker in s.get('markers',[]):marker['closed']=True
            if s.get('transition'):
                t=s.pop('transition'); t.update({'complete':False,'verdict':'inconclusive','reason':'Session ended before WAN confirmation.'}); s['transitions'].append(t)
            s['status']='completed'; s['ended']=time.time(); s['duration']=elapsed(s); event(s,'finish','Session finished'); STOP.set(); ACTIVE=None
        elif action=='note':
            note=str(body.get('note','')).strip()[:1000]
            if not note: raise ValueError('Enter a note')
            event(s,'note',note)
        else: raise ValueError('Unknown action')
        save(s); return s


def start_job(body):
    global JOB
    with LOCK:
        if not ACTIVE: raise ValueError('Start a session to record diagnostics')
        if JOB and JOB['status']=='running': raise ValueError('A diagnostic is already running')
        s=get_session(ACTIVE)
        kind=body.get('kind')
        if kind not in ['speed','mtr','identity','ping']: raise ValueError('Unknown diagnostic')
        if s['phase'] in ['failover','failback'] and kind!='identity': raise ValueError('Run diagnostics after confirming the active WAN to keep timing measurements clean')
        if kind=='mtr' and not TOOLS['mtr']: raise ValueError('MTR is not installed')
        wan_label=s['wan']
        if s['mode']=='recording':
            last=s.get('router_latest',{})
            wan_label=last.get('active_path','Unknown') if last.get('ok') and elapsed(s)-last['t']<5 else 'Unknown'
        job={'id':uuid.uuid4().hex[:10],'kind':kind,'status':'running','started':time.time(),'phase':s['phase'],'wan':wan_label,'session':s['id']}
        JOB=job; s['jobs'].append(job.copy()); event(s,'diagnostic',f'{kind.upper()} started'); save(s)
        threading.Thread(target=job_worker,args=(job.copy(),s),daemon=True).start()
        return job


def job_worker(job,s):
    global JOB
    try:
        iface=s['interface']; kind=job['kind']
        if kind=='identity':
            result=identity(iface)
            if result.get('error'): raise ValueError(result['error'])
            job['result']=result
        elif kind=='speed':
            code,out,err=run([TOOLS['networkQuality'],'-c','-s','-I',iface,'-M','90'],110)
            try: raw=json.loads(out[out.index('{'):])
            except (ValueError, json.JSONDecodeError): raise ValueError(err.strip() or out[-500:] or 'No speed-test result')
            if code: raise ValueError(err.strip() or str(raw.get('error','Speed test failed')))
            job['result']={'download':raw.get('dl_throughput',0)/1e6,'upload':raw.get('ul_throughput',0)/1e6,'latency':raw.get('base_rtt'),'provider':'Apple networkQuality','raw':raw}
            if not raw.get('dl_throughput') or not raw.get('ul_throughput'): raise ValueError('Speed test returned incomplete throughput results; please retry')
        elif kind=='mtr':
            code,out,err=run([TOOLS['mtr'],'-4','--json','--report-cycles','10','--interval','1','--max-ttl','20','--no-dns','--address',s['local_ip'],'1.1.1.1'],35)
            if code: raise ValueError(err.strip() or 'MTR failed')
            job['result']={'raw':json.loads(out),'target':'1.1.1.1','binding':'source IPv4 address'}
        else:
            code,out,err=run([TOOLS['ping'],'-n','-c','20','-i','0.2','-W','700','-b',iface,'1.1.1.1'],12)
            if code not in [0,2]: raise ValueError(err.strip() or 'Ping failed')
            job['result']={'output':out,'target':'1.1.1.1'}
        job['status']='completed'
    except Exception as e:
        job['status']='failed'; job['error']=str(e)[:1500]
    finally:
        job['ended']=time.time()
        with LOCK:
            current=get_session(s['id'])
            if job['kind']=='identity' and job['status']=='completed':
                ident={**job['result'],'wan':current['wan'],'phase':current['phase']}; current['identities'].append(ident)
            current['jobs']=[job if j['id']==job['id'] else j for j in current['jobs']]
            event(current,'diagnostic',f'{job["kind"].upper()} {job["status"]}')
            if job['kind']=='speed': current['stable']=0; current.pop('last_sample_t',None); current.pop('last_sample_wall',None)
            save(current); JOB=job


def summary(s):
    q=s['stats']; n=q['received']
    return {'avg_ms':round(q['sum']/n,2) if n else None,'loss_pct':round(q['lost']/q['sent']*100,2) if q['sent'] else None,'jitter_ms':round(q['jitter_sum']/q['jitter_n'],2) if q['jitter_n'] else None,'min_ms':q['min'],'max_ms':q['max']}


def public_session(s):
    result = {**{k:v for k,v in s.items() if not k.startswith('_')},'summary':summary(s),'elapsed':elapsed(s) if s['status']=='running' else s.get('duration',0)}
    if s.get('mode') == 'recording':
        from recording_report import derive_recording
        result = derive_recording(result, samples(s['id']))
    from wan_labels import apply_labels
    return apply_labels(result, router_samples(s['id']))


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send(self,data,status=200,ctype='application/json',filename=None):
        if ctype=='application/json': data=json.dumps(data).encode()
        elif isinstance(data,str): data=data.encode()
        self.send_response(status); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        if filename: self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers(); self.wfile.write(data)
    def trusted(self):
        return self.headers.get('Host') in [f'127.0.0.1:{PORT}',f'localhost:{PORT}']
    def do_GET(self):
        if not self.trusted(): return self.send({'error':'Invalid host'},403)
        path=urlparse(self.path).path; query=parse_qs(urlparse(self.path).query)
        try:
            if path=='/api/config': return self.send({'app':'Router Lab','token':TOKEN,'network':network(),'tools':{k:bool(v) for k,v in TOOLS.items()},'router_credentials_host':router_credentials().get('host'),'version':'1.1.0'})
            with LOCK:
                if path=='/api/state':
                    sid=query.get('id',[ACTIVE])[0]
                    s=get_session(sid) if sid else None
                    return self.send({'active':ACTIVE,'session':public_session(s) if s else None,'samples':samples(sid,300) if s else [],'job':JOB})
                if path=='/api/history':
                    docs=[public_session(json.loads(r[0])) for r in DB.execute('SELECT doc FROM sessions ORDER BY rowid DESC')]
                    return self.send(docs)
                if path in ['/api/export','/api/report']:
                    sid=query.get('id',[''])[0]; s=public_session(get_session(sid)); rows=samples(sid); rrows=router_samples(sid)
                    fmt=query.get('format',['json'])[0]
                    if path=='/api/report':
                        from report import build_pdf
                        return self.send(build_pdf(s,rows,rrows),ctype='application/pdf',filename=f'router-lab-{sid}.pdf')
                    if fmt=='csv':
                        buf=io.StringIO(); w=csv.writer(buf); w.writerow(['record','time_seconds','timestamp','phase','loaded','target','ok','latency_ms','details'])
                        w.writerow(['metadata','','','','','','','',json.dumps(s)])
                        for p in rows:
                            for key in ['router','cloudflare','google','dns','web']:
                                w.writerow(['sample',p['t'],p['at'],p['phase'],p['loaded'],key,p[key]['ok'],p[key]['ms'],p[key].get('error')])
                        for r in rrows:
                            w.writerow(['router_status',r['t'],r['at'],r['phase'],'','router_api',r['ok'],r['latency_ms'],json.dumps(r)])
                        for e in s['events']:
                            # Prevent formula execution in spreadsheet applications.
                            label=e['label']; label="'"+label if label.startswith(('=','+','-','@')) else label
                            w.writerow(['event',e['t'],e['at'],'','','','', '',label])
                        return self.send(buf.getvalue(),ctype='text/csv',filename=f'router-lab-{sid}.csv')
                    return self.send({'session':s,'samples':rows,'router_samples':rrows},ctype='application/json',filename=f'router-lab-{sid}.json')
            files={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css'),'/favicon.svg':('favicon.svg','image/svg+xml')}
            if path not in files: return self.send({'error':'Not found'},404)
            name,ctype=files[path]; self.send((ROOT/'static'/name).read_bytes(),ctype=ctype)
        except ValueError as e: self.send({'error':str(e)},400)
        except Exception as e: self.send({'error':str(e)},500)
    def do_POST(self):
        if not self.trusted() or self.headers.get('X-Lab-Token')!=TOKEN: return self.send({'error':'Invalid request token'},403)
        origin=self.headers.get('Origin')
        if origin and origin not in [f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}']: return self.send({'error':'Invalid origin'},403)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=16000: raise ValueError('Invalid request size')
            body=json.loads(self.rfile.read(size))
            if not isinstance(body,dict): raise ValueError('Expected JSON object')
            path=urlparse(self.path).path
            if path=='/api/start': result=start_session(body)
            elif path=='/api/action': result=do_action(body)
            elif path=='/api/job': result=start_job(body)
            else: return self.send({'error':'Not found'},404)
            self.send(result)
        except (ValueError,TypeError) as e: self.send({'error':str(e)},400)
        except Exception as e: self.send({'error':str(e)},500)


def main():
    with LOCK:
        for row in DB.execute('SELECT doc FROM sessions').fetchall():
            s=json.loads(row[0])
            if s['status']=='running':
                s['status']='interrupted'; s['duration']=s.get('last_sample_t',0); s['ended']=time.time()
                for j in s['jobs']:
                    if j['status']=='running': j['status']='failed'; j['error']='Service stopped during diagnostic'
                s['events'].append({'kind':'error','label':'Service restarted; session marked interrupted','t':s['duration'],'at':time.time()}); save(s)
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    print(f'Router Lab ready: http://127.0.0.1:{PORT}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: STOP.set(); server.server_close()

if __name__=='__main__': main()
