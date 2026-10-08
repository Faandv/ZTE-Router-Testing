"""Regression tests for measurement semantics and request safety; uses isolated storage."""
import os
import tempfile
import time
import unittest
from unittest.mock import patch
os.environ['ROUTER_LAB_DATA']=tempfile.mkdtemp(prefix='router-lab-tests-')
import server

def fixture():
    return {'id':'fixture','name':'Test','router':'ZTE G5TS Pro','firmware':'test','notes':'','mode':'guided','wan':'Fibre','wan_source':'manually confirmed','interface':'en0','connection':'Wi-Fi','gateway':'192.168.0.1','local_ip':'192.168.0.2','status':'running','phase':'fibre_baseline','started':time.time(),'_mono':time.monotonic(),'count':0,'events':[],'outages':[],'transitions':[],'jobs':[],'identities':[],'stable':0,'max_gap':0,'stats':{'sent':0,'lost':0,'sum':0,'received':0,'min':None,'max':None,'previous':{},'jitter_sum':0,'jitter_n':0}}

def sample(t,ok=True,loaded=False,cf=10,google=30):
    def probe(ms):return {'ok':ok,'ms':ms if ok else None,'error':None}
    return {'seq':int(t),'probe_start':t-.1,'t':t,'at':time.time(),'phase':'failover','loaded':loaded,'router':probe(1),'cloudflare':probe(cf),'google':probe(google),'web':probe(100),'dns':probe(1)}

class TimingTests(unittest.TestCase):
    def setUp(self):server.ACTIVE=None;server.JOB=None;self.s=fixture()
    def feed(self,*items):
        for p in items:server.process_sample(self.s,p)
    def marker(self,t=3):self.s['phase']='failover';self.s['transition']={'kind':'failover','marker':t,'complete':False,'saw_failure':False}
    def test_recovery_requires_three_samples(self):
        self.feed(sample(1),sample(2),sample(3));self.marker()
        self.feed(sample(4,False),sample(5,False),sample(6),sample(7))
        self.assertNotIn('recovered',self.s['transition'])
        self.feed(sample(8));self.assertEqual(self.s['transition']['marker_to_recovery'],5)
        self.assertEqual(self.s['outages'][0]['duration'],2)
    def test_healthy_stream_does_not_prove_switch(self):
        self.marker();self.feed(sample(4),sample(5),sample(6))
        self.assertNotIn('recovered',self.s['transition'])
        server.save(self.s);server.ACTIVE='fixture'
        result=server.do_action({'action':'confirm_5g'})
        self.assertEqual(result['transitions'][0]['verdict'],'inconclusive')
    def test_exactly_sixty_seconds_fails(self):
        self.marker();self.feed(*[sample(t,False) for t in range(4,61)],sample(61),sample(62),sample(63))
        server.save(self.s);server.ACTIVE='fixture'
        self.assertEqual(server.do_action({'action':'confirm_5g'})['transitions'][0]['verdict'],'fail')
    def test_less_than_sixty_passes_after_confirmation(self):
        self.marker();self.feed(*[sample(t,False) for t in range(4,59)],sample(59),sample(60),sample(61))
        server.save(self.s);server.ACTIVE='fixture'
        self.assertEqual(server.do_action({'action':'confirm_5g'})['transitions'][0]['verdict'],'pass')
    def test_monitor_gap_makes_timing_inconclusive(self):
        self.marker();self.feed(sample(4,False),sample(25),sample(26),sample(27))
        server.save(self.s);server.ACTIVE='fixture'
        self.assertEqual(server.do_action({'action':'confirm_5g'})['transitions'][0]['verdict'],'inconclusive')
    def test_loaded_samples_do_not_create_outage(self):
        self.feed(sample(1),sample(2,False,True));self.assertNotIn('outage',self.s)
    def test_single_lucky_reply_does_not_close_outage(self):
        self.feed(sample(1),sample(2,False),sample(3),sample(4,False));self.assertFalse(self.s['outages'])
    def test_jitter_is_calculated_per_destination(self):
        self.feed(sample(1),sample(2));self.assertEqual(server.summary(self.s)['jitter_ms'],0)
    def test_web_success_required(self):
        p=sample(1);p['web']['ok']=False;self.feed(p);self.assertEqual(self.s['stable'],0)
    def test_one_public_ping_sufficient(self):
        p=sample(1);p['google']['ok']=False;p['google']['ms']=None;self.feed(p);self.assertEqual(self.s['stable'],1)
    def test_pending_probe_cannot_prove_transition(self):
        self.marker(3);p=sample(4,False);p['probe_start']=2;self.feed(p);self.assertFalse(self.s['transition']['saw_failure'])
    def test_unfinished_transition_inconclusive(self):
        self.marker();server.save(self.s);server.ACTIVE='fixture'
        result=server.do_action({'action':'finish'});self.assertEqual(result['transitions'][0]['verdict'],'inconclusive')
    def test_speed_forbidden_during_transition(self):
        self.marker();server.save(self.s);server.ACTIVE='fixture'
        with self.assertRaises(ValueError):server.start_job({'kind':'speed'})
    def test_guided_requires_fibre(self):
        info={'interfaces':[{'device':'en0','ip':'192.168.0.2','active':True,'gateway':'192.168.0.1','kind':'Wi-Fi'}],'default':'en0'}
        with patch.object(server,'network',return_value=info):
            with self.assertRaises(ValueError):server.start_session({'interface':'en0','mode':'guided','wan':'5G'})
    def test_gateway_rejects_command_injection(self):
        info={'interfaces':[{'device':'en0','ip':'192.168.0.2','active':True,'gateway':'192.168.0.1','kind':'Wi-Fi'}]}
        with patch.object(server,'network',return_value=info):
            with self.assertRaises(ValueError):server.start_session({'interface':'en0','gateway':'127.0.0.1; whoami'})
    def test_pdf_generates_readable_pages(self):
        from report import build_pdf
        from pypdf import PdfReader
        import io
        self.feed(sample(1),sample(2),sample(3))
        data=build_pdf(server.public_session(self.s),[sample(1),sample(2),sample(3)])
        text=''.join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)
        self.assertIn('No completed transition measurement',text)
        self.assertIn('Measurement method',text)



class RecordingTests(unittest.TestCase):
    def setUp(self):
        server.ACTIVE='fixture';server.JOB=None;self.s=fixture();self.s.update({'mode':'recording','markers':[],'router_capture':True});server.save(self.s)
    def test_markers_repeat_without_inventing_wan(self):
        for action in ['wan_plugged','wan_unplugged','wan_plugged']:server.do_action({'action':action})
        s=server.get_session('fixture');self.assertEqual(len(s['markers']),3);self.assertEqual(s['wan'],'Unknown');self.assertTrue(s['markers'][1]['closed'])
    def test_marker_works_during_speed_but_timing_flagged(self):
        server.JOB={'status':'running','kind':'speed'}
        s=server.do_action({'action':'wan_unplugged'});self.assertTrue(s['markers'][0]['timing_unreliable'])
    def test_marker_recovery_and_no_switch_claim(self):
        s=server.do_action({'action':'wan_unplugged'});s['markers'][0]['t']=0
        for p in [sample(1,False),sample(2),sample(3),sample(4)]:
            server.process_sample(s,p);server.record_marker_progress(s,p)
        self.assertEqual(s['markers'][0]['marker_to_recovery'],4)
        self.assertNotIn('verdict',s['markers'][0])
    def test_api_failure_does_not_erase_last_good(self):
        good={'ok':True,'t':1,'at':time.time(),'active_path':'Mobile','wan':{'opms_wan_mode':'AUTO'},'mobile':{},'device':{}}
        server.process_router_snapshot(self.s,good)
        server.process_router_snapshot(self.s,{'ok':False,'t':2,'error':'Timed out'})
        self.assertEqual(self.s['router_last_good'],good);self.assertEqual(self.s['router_failures'],1)
    def test_raw_changes_have_observation_bounds(self):
        a={'ok':True,'t':1,'active_path':'Unknown','wan':{'opms_wan_mode':'AUTO','mwan_wanlan1_link_state':'port_out'},'mobile':{},'device':{}}
        b={**a,'t':2,'wan':{**a['wan'],'mwan_wanlan1_link_state':'port_in'}}
        server.process_router_snapshot(self.s,a);server.process_router_snapshot(self.s,b)
        e=self.s['events'][-1];self.assertEqual(e['observed_between'],[1,2]);self.assertEqual(e['field'],'mwan_wanlan1_link_state')
    def test_duplicated_wan_ip_does_not_prove_fibre(self):
        from router_client import interpret
        r=interpret({'current_wan_interface':'wan1','current_wan_status':'ipv4_connected','mwan_wanlan1_wan_ipaddr':'1.2.3.4'},{'ipv4_dev_name':'wan1','connect_status':'ipv4_connected','ipv4_address':'1.2.3.4'},{'network_type':'ENDC'})
        self.assertEqual(r['active_path'],'Mobile / 5G NSA');self.assertTrue(r['wan_fields_overlap'])
    def test_unknown_interface_is_not_classified_by_ip(self):
        from router_client import interpret
        self.assertEqual(interpret({'current_wan_interface':'other','current_wan_status':'ipv4_connected'}, {'ipv4_dev_name':'wan1'}, {})['active_path'],'Unknown')
    def test_adapter_rejects_configuration_writes(self):
        from router_client import RouterClient
        c=RouterClient('192.168.0.1','192.168.0.2','test')
        with self.assertRaises(ValueError):c.rpc([('zwrt_router.api','router_set_dhcp_mode',{})])
    def test_router_target_must_be_private(self):
        from router_client import RouterClient
        with self.assertRaises(ValueError):RouterClient('8.8.8.8','192.168.0.2','test')



class RecordingReportTests(unittest.TestCase):
    def test_report_includes_markers_and_router_evidence(self):
        from report import build_pdf
        from pypdf import PdfReader
        import io
        s=fixture();s['mode']='recording';s['markers']=[{'id':1,'label':'WAN unplugged','t':2,'first_failure':3,'recovered':8,'marker_to_recovery':6,'closed':True}]
        s['outages']=[{'phase':'test','first_failure':3,'first_recovered':6,'recovered':8,'duration':3}]
        s['router_count']=1;s['router_successes']=1;s['router_failures']=0
        s['router_last_good']={'t':1,'active_path':'Mobile / 5G NSA','path_evidence':'Cellular interface match','wan':{'opms_wan_mode':'AUTO'},'radio':{},'wan_fields_overlap':True}
        doc=PdfReader(io.BytesIO(build_pdf(server.public_session(s),[])))
        text=''.join(p.extract_text() for p in doc.pages)
        for phrase in ['Cable markers','WAN unplugged','6.000s','Router status capture','Firmware ambiguity']:self.assertIn(phrase,text)



class MarkerAcknowledgementTests(unittest.TestCase):
    def setUp(self):
        server.ACTIVE='fixture';server.JOB=None;s=fixture();s.update({'mode':'recording','markers':[]});server.save(s)
    def test_same_request_id_returns_original_marker(self):
        first=server.do_action({'action':'wan_plugged','request_id':'click-1'})
        server.do_action({'action':'wan_unplugged','request_id':'click-2'})
        retry=server.do_action({'action':'wan_plugged','request_id':'click-1'})
        self.assertEqual(len(retry['markers']),2);self.assertTrue(retry['marker_duplicate'])
        for key in ('id','t','at','request_id','action'):
            self.assertEqual(retry['marker_ack'][key],first['marker_ack'][key])
    def test_double_click_creates_one_marker(self):
        server.do_action({'action':'wan_plugged','request_id':'a'})
        result=server.do_action({'action':'wan_plugged','request_id':'b'})
        self.assertEqual(len(result['markers']),1);self.assertTrue(result['marker_duplicate'])
    def test_opposite_action_is_not_delayed(self):
        server.do_action({'action':'wan_plugged','request_id':'a'})
        result=server.do_action({'action':'wan_unplugged','request_id':'b'})
        self.assertEqual(len(result['markers']),2);self.assertFalse(result['marker_duplicate']);self.assertIn('at',result['marker_ack'])
    def test_stale_session_is_rejected(self):
        with self.assertRaises(ValueError):server.do_action({'action':'wan_plugged','session_id':'old'})
    def test_new_same_action_after_cooldown_is_allowed(self):
        server.do_action({'action':'wan_plugged','request_id':'a'})
        s=server.get_session('fixture');s['markers'][0]['t']-=3;server.save(s)
        result=server.do_action({'action':'wan_plugged','request_id':'b'})
        self.assertEqual(len(result['markers']),2)

class AttributionTests(unittest.TestCase):
    def derive(self, failure=9.954, recovery=13.32, rows=None, markers=None):
        from recording_report import derive_recording
        s=fixture();s.update(mode='recording',status='completed',duration=50,
            markers=markers or [{'id':1,'label':'WAN plugged in','t':1,'closed':True},
                                {'id':2,'label':'WAN unplugged','t':10,'closed':True}],
            outages=[{'phase':'wan_plugged_1','first_failure':failure,
                      'first_recovered':recovery-2,'recovered':recovery,'duration':recovery-2-failure}])
        self.original=s
        return derive_recording(s,rows or [])
    def test_failure_just_before_click_moves_to_new_marker(self):
        d=self.derive();m=d['markers'][1]
        self.assertEqual(m['marker_to_recovery'],3.32)
        self.assertIn('0.046s before click',m['observation_text'])
        self.assertNotIn('first_failure',d['markers'][0])
        self.assertEqual(d['outages'][0]['associated_marker'],2)
        self.assertEqual(self.original['outages'][0]['phase'],'wan_plugged_1')
        self.assertNotIn('associated_marker',self.original['outages'][0])
    def test_completed_outage_not_stolen_by_later_click(self):
        d=self.derive(failure=8,recovery=9)
        self.assertEqual(d['outages'][0]['associated_marker'],1)
    def test_old_ongoing_outage_is_not_relabelled(self):
        d=self.derive(failure=4)
        self.assertIn('Older interruption',d['markers'][1]['observation_text'])
        self.assertTrue(d['markers'][0]['timing_unreliable'])
    def test_inflight_failure_after_click_counts(self):
        d=self.derive(failure=10.2)
        self.assertEqual(d['markers'][1]['first_failure'],10.2)
    def test_load_after_recovery_does_not_invalidate_timing(self):
        d=self.derive(rows=[sample(20,loaded=True)])
        self.assertFalse(d['markers'][1]['timing_unreliable'])
    def test_load_during_recovery_is_inconclusive(self):
        d=self.derive(rows=[sample(11,loaded=True)])
        self.assertTrue(d['markers'][1]['timing_unreliable'])
    def test_gap_during_recovery_is_inconclusive(self):
        d=self.derive(recovery=22,rows=[sample(10),sample(21)])
        self.assertTrue(d['markers'][1]['timing_unreliable'])
    def test_multiple_interruptions_retained(self):
        from recording_report import derive_recording
        self.derive();s=self.original
        s['outages'].append({'phase':'wan_unplugged_2','first_failure':30,'first_recovered':31,'recovered':33,'duration':1})
        d=derive_recording(s,[])
        self.assertEqual(len(d['markers'][1]['observations']),2)
    def test_open_interruption_reported(self):
        from recording_report import derive_recording
        self.derive();s=self.original;s['outage']=s['outages'].pop()
        s['outage'].pop('recovered');s['outage'].pop('first_recovered')
        d=derive_recording(s,[])
        self.assertIn('stable recovery not recorded',d['markers'][1]['observation_text'])

if __name__=='__main__':unittest.main(verbosity=2)
