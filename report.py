"""PDF reports generated on demand; no cloud service needed."""
import io
import json
from datetime import datetime
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak
from reportlab.graphics.shapes import Drawing, Line, String, PolyLine, Rect

GREEN=colors.HexColor('#187b62'); INK=colors.HexColor('#193b37'); MUTED=colors.HexColor('#71867c'); LINE=colors.HexColor('#dce7df')

def build_pdf(s, rows, router_rows=None):
    out=io.BytesIO()
    doc=SimpleDocTemplate(out,pagesize=(595.28,841.89),rightMargin=42,leftMargin=42,topMargin=48,bottomMargin=43,title=f'Router Lab - {s["name"]}',author='Router Lab')
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='TitleLab',fontName='Helvetica',fontSize=25,leading=30,textColor=INK,spaceAfter=10))
    styles.add(ParagraphStyle(name='SectionLab',fontName='Helvetica-Bold',fontSize=12,leading=16,textColor=INK,spaceBefore=15,spaceAfter=9,keepWithNext=True))
    styles.add(ParagraphStyle(name='BodyLab',fontSize=9,leading=13,textColor=INK,spaceAfter=7))
    styles.add(ParagraphStyle(name='SmallLab',fontSize=7.5,leading=10.5,textColor=MUTED,spaceAfter=6))
    def p(t,style='BodyLab'): return Paragraph(escape(str(t)).replace('\n','<br/>'),styles[style])
    def section(t): return p(t,'SectionLab')
    def number(v,d=1): return '-' if v is None else f'{v:.{d}f}'
    def date(t): return datetime.fromtimestamp(t).strftime('%d %b %Y, %H:%M:%S')
    def table(data,widths=None):
        cells=[[p(v,'SmallLab' if i==0 else 'BodyLab') for v in row] for i,row in enumerate(data)]
        t=Table(cells,colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf4ee')),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.6,LINE),('LINEBELOW',(0,1),(-1,-1),.3,LINE),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        return t
    story=[p('ROUTER LAB  /  NETWORK VALIDATION','SmallLab'),p(s['name'],'TitleLab'),p(f'{s["router"]} | {s["connection"]} ({s["interface"]}) | {s["status"].upper()}'),p(f'Started {date(s["started"])} | Session {s["id"]} | Duration {number(s.get("elapsed",s.get("duration",0)))} seconds','SmallLab')]
    story.append(table([['Router / firmware','WAN identification','Test configuration'],[f'{s["gateway"]}\nFirmware: {s["firmware"] or "Not recorded"}',f'{s["wan"]} - {s["wan_source"]}',f'Mode: {s["mode"]}\nIPv4; target cadence 1 second\nRecovery target < 60 seconds']],[170,170,171]))
    if s.get('notes'): story.append(p('Notes: '+s['notes']))
    if s.get('vpn_detected'): story.append(p(f'VPN caveat: default route at session start was {s.get("default_route")}. Interface binding was requested where supported; VPN policy and DNS may still influence results.','SmallLab'))
    q=s['summary']
    story += [section('Connection quality'),table([['Average latency','Public packet loss','Jitter','Samples'],[number(q['avg_ms'])+' ms',number(q['loss_pct'])+'%',number(q['jitter_ms'])+' ms',s['count']]],[128,128,128,127]),p('Aggregates cover both public ping targets and all samples, including speed-test load. Jitter is the mean absolute change between successive successful RTTs per target.','SmallLab')]
    if rows:
        d=Drawing(511,165); left=34; bottom=23; width=466; height=126
        vals=[r[k]['ms'] for r in rows for k in ['cloudflare','google','router'] if r[k]['ms'] is not None]
        maximum=max([20]+vals); start=rows[0]['t']; span=max(1,rows[-1]['t']-start)
        for n in range(5):
            y=bottom+height*n/4; d.add(Line(left,y,500,y,strokeColor=LINE,strokeWidth=.5)); d.add(String(left-5,y-2,str(round(maximum*n/4)),fontSize=7,fillColor=MUTED,textAnchor='end'))
        stride=max(1,len(rows)//700)
        for key,color in [('router','#c6a369'),('google','#90b8a2'),('cloudflare','#248668')]:
            points=[]
            for r in rows[::stride]:
                if r[key]['ms'] is None:
                    if len(points)>=4:d.add(PolyLine(points,strokeColor=colors.HexColor(color),strokeWidth=.8))
                    points=[];continue
                points.extend([left+(r['t']-start)/span*width,bottom+r[key]['ms']/maximum*height])
            if len(points)>=4:d.add(PolyLine(points,strokeColor=colors.HexColor(color),strokeWidth=.8))
        d.add(String(left,5,f'{start:.0f}s',fontSize=7,fillColor=MUTED));d.add(String(500,5,f'{rows[-1]["t"]:.0f}s',fontSize=7,fillColor=MUTED,textAnchor='end'))
        story += [Spacer(1,10),d,p('Latency (ms) across elapsed seconds. Dark green: Cloudflare; light green: Google; gold: router. Long sessions are downsampled for the chart; CSV/JSON retain every sample.','SmallLab')]
    story.append(section('Failover and fibre recovery'))
    if s['transitions']:
        story.append(table([['Transition','Marker to stable recovery','Result / interpretation']]+[[t['kind'],number(t.get('marker_to_recovery'))+' s',t['verdict'].upper()+': '+t['reason']] for t in s['transitions']],[75,110,326]))
    elif s.get('mode')=='recording': story.append(p('Cable-marker recovery measurements are listed below. They describe connectivity recovery; active WAN evidence is recorded separately.'))
    else: story.append(p('No completed transition measurement. Baseline sessions do not establish failover performance.'))
    if s.get('transition'): story.append(p('A transition is still in progress. This report is provisional.'))
    story.append(p(f'Manual marker time is the moment the server receives the click, not the physical cable event. Recovery requires three consecutive samples with a successful HTTPS request and at least one public ping reply. Reported pass/fail applies only to manual-marker-to-stable-recovery time. No observed interruption is inconclusive. Largest sampling gap: {number(s.get("max_gap"),2)} seconds. No hardware WAN timestamps are available.','SmallLab'))
    story.append(section('Observed interruptions'))
    if s['outages']:
        story.append(table([['Phase','First failure','First healthy sample','Sampled outage']]+[[o.get('report_phase',o['phase']),number(o['first_failure'],3)+' s',number(o['first_recovered'],3)+' s',number(o['duration'],3)+' s'] for o in s['outages']],[130,115,140,126]))
    else: story.append(p('No recovered interruptions recorded.'))
    if s.get('outage'): story.append(p(f'An interruption remains open from +{number(s["outage"]["first_failure"])}s.'))
    story.append(p('Sampled outage = first failed sample completion to first healthy sample in the eventual stable recovery sequence. These are sampled observations, not an exact physical outage duration. Router reachability is reported separately; local-link failures can affect the result.','SmallLab'))
    story.append(section('External public IP lookup snapshots'))
    if s['identities']: story.append(table([['Time / WAN','Public IP','Provider / ASN']]+[[date(i['at'])+' / '+i['wan'],i['ip'],f'{i.get("isp","Unknown")} / AS{i.get("asn","?")}'] for i in s['identities']],[185,130,196]))
    else: story.append(p('No public IP snapshots captured.'))
    story.append(p('WAN labels are manually confirmed. Public IP/provider differences can support WAN identification but are not definitive proof. IP lookup provider: ipwho.is.','SmallLab'))
    if s.get('mode')=='recording':
        story.append(section('Cable markers and recording results'))
        if s.get('markers'):
            data=[['Marker','Elapsed','Connectivity observation']]
            for m in s['markers']:
                result=m.get('observation_text') or ('Timing inconclusive: monitoring gap or speed-test load' if m.get('timing_unreliable') else (f"Stable internet recovered {m['marker_to_recovery']:.3f}s after marker" if m.get('recovered') is not None else ('Interruption seen; recovery not recorded' if m.get('first_failure') is not None else 'No interruption observed in this marker window')))
                data.append([f"M{m['id']} - {m['label']}",f"+{m['t']:.3f}s",result])
            story.append(table(data,[145,75,291]))
        else:story.append(p('No cable markers recorded.'))
        if s.get('attribution_method'): story.append(p(s['attribution_method'],'SmallLab'))
        story.append(p('Markers record receipt of a manual click, not a hardware cable event. Connectivity recovery does not alone establish which WAN carried traffic.','SmallLab'))
        story.append(section('Router status capture'))
        story.append(p(f"{s.get('router_successes',0)} successful snapshots; {s.get('router_failures',0)} failed requests; {s.get('router_changes',0)} observed WAN field changes. Target interval: 1 second. No router settings were changed by the recorder."))
        r=s.get('router_last_good')
        if r:
            w=r.get('wan',{});radio=r.get('radio',{})
            story.append(table([['Last successful reading','Value'],['Observed at',f"+{r['t']:.3f}s"],['Router-reported path',r['active_path']],['Evidence',r['path_evidence']],['Operating mode',str(w.get('opms_wan_mode'))+' / '+str(w.get('opms_wan_auto_mode'))],['WAN link / connection fields',str(w.get('mwan_wanlan1_link_state'))+' / '+str(w.get('mwan_wanlan1_status'))],['WAN IP field',w.get('mwan_wanlan1_wan_ipaddr','')],['Mobile signal',f"{radio.get('network_provider','')} / {radio.get('nr5g_action_band','')} / RSRP {radio.get('nr5g_rsrp','')} dBm / SINR {radio.get('nr5g_snr','')} dB"]],[160,351]))
            if r.get('wan_fields_overlap'):story.append(p('Firmware ambiguity: the WAN IP field repeats the mobile IP and no separate wired interface is reported. These raw fields do not prove a physical fibre connection.','SmallLab'))
        story.append(p('This is a timestamped status recording, not a firmware syslog download. CPU, memory, hardware reboot timestamps and exact WAN-event timestamps are not available in the verified calls. API failures are separate from router ping and internet failures. Every status snapshot is included in CSV/JSON; the timeline below lists significant changes.','SmallLab'))
    story.append(section('Diagnostic results'))
    if not s['jobs']: story.append(p('No individual diagnostics run.'))
    for j in s['jobs']:
        story.append(p(f'{j["kind"].upper()} | {j["wan"]} | {date(j["started"])} | {j["status"]}', 'SectionLab'))
        if j.get('error'): story.append(p(j['error']));continue
        r=j.get('result')
        if not r: story.append(p('Diagnostic still running.'));continue
        if j['kind']=='speed':
            story.append(table([['Engine','Download','Upload','Idle latency'],[r['provider'],number(r['download'])+' Mbps',number(r['upload'])+' Mbps',number(r['latency'])+' ms']],[175,112,112,112]))
            story.append(p('Sequential download/upload testing, maximum runtime 90 seconds. Results depend on the selected interface, server and network conditions. Raw engine output is included in JSON exports.','SmallLab'))
        elif j['kind']=='mtr':
            hubs=r['raw'].get('report',{}).get('hubs',[])
            story.append(table([['Hop','Host','Loss %','Sent','Avg ms','Worst ms']]+[[h.get('count'),h.get('host'),h.get('Loss%'),h.get('Snt'),h.get('Avg'),h.get('Wrst')] for h in hubs],[35,190,65,50,80,91]))
            story.append(p('Target: 1.1.1.1. Intermediate routers may rate-limit or suppress ICMP replies. Hop loss without matching destination loss does not demonstrate traffic loss.','SmallLab'))
        elif j['kind']=='ping':
            for line in r['output'].splitlines(): story.append(p(line,'SmallLab'))
        else: story.append(p(json.dumps(r),'SmallLab'))
    story.append(section('Timeline'))
    story.append(table([['Elapsed','Local timestamp','Event']]+[[f'+{e["t"]:.3f}s',date(e['at']),e['label']] for e in s['events']],[67,132,312]))
    story += [KeepTogether([section('Measurement method'),p('Targets: ICMP to the configured router, Cloudflare 1.1.1.1 and Google 8.8.8.8; HTTPS to example.com; DNS query for example.com using the Mac resolver configuration. Probes run concurrently with a target cadence of one second. Slow probes can extend the actual interval. DNS is recorded independently and is not part of the stable recovery rule. Tests cover IPv4 only.','SmallLab'),p('Speed-test samples are excluded from outage detection. MTR binds to the selected source IPv4 address; ping, HTTPS and speed tests request the selected interface. The service uses monotonic elapsed timing. Laptop sleep, route changes, VPNs, cached DNS and endpoint-specific failures can influence interpretation. Reports are snapshots; JSON and CSV preserve all underlying observations.','SmallLab')])]
    def footer(canvas,doc):
        canvas.setStrokeColor(LINE);canvas.line(42,32,553,32);canvas.setFont('Helvetica',7);canvas.setFillColor(MUTED);canvas.drawString(42,20,'Router Lab | Local report | '+s['id']);canvas.drawRightString(553,20,f'Page {doc.page}')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()
