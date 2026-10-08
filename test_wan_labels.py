import unittest
from copy import deepcopy
from router_client import interpret
from wan_labels import apply_labels
class WANLabels(unittest.TestCase):
 def setUp(self):
  self.w=dict(current_wan_status='ipv4_connected',current_wan_interface='eth0.2',opms_wan_mode='AUTO',opms_wan_auto_mode='AUTO_DHCP',mwan_wanlan1_link_mode='DHCP',mwan_wanlan1_status='ipv4_connected',mwan_wanlan1_wan_ifname='',mwan_wanlan1_wan_ipaddr='192.0.2.20')
  self.m=dict(ipv4_dev_name='wan1',ipv4_address='198.51.100.20',connect_status='ipv4_connected')
 def label(self):return interpret(self.w,self.m,{'network_type':'ENDC'})['active_path']
 def test_dhcp(self):self.assertEqual(self.label(),'Wired WAN - DHCP (inferred)')
 def test_conflicts(self):
  for k,v in [('current_wan_interface',''),('current_wan_interface','other'),('opms_wan_auto_mode','AUTO_PPPOE'),('current_wan_status','disconnected'),('mwan_wanlan1_wan_ipaddr','0.0.0.0'),('mwan_wanlan1_wan_ipaddr',self.m['ipv4_address']),('mwan_wanlan1_wan_ifname','different')]:
   with self.subTest(k=k,v=v):
    old=self.w[k];self.w[k]=v;self.assertEqual(self.label(),'Unknown');self.w[k]=old
 def test_mobile(self):
  self.w['current_wan_interface']='wan1';self.assertEqual(self.label(),'Mobile / 5G NSA')
 def test_explicit(self):
  self.w['mwan_wanlan1_wan_ifname']='eth0.2';self.assertEqual(self.label(),'Wired WAN')
 def session(self):
  r=dict(ok=True,t=10,probe_start=9.9,at=110,wan=self.w,mobile=self.m,radio={},active_path='Unknown')
  return dict(router_capture=True,router_latest=r,router_last_good=r,elapsed=11,wan='Unknown',jobs=[dict(started=111,wan='Unknown')]),[r]
 def test_history(self):
  s,rows=self.session();before=deepcopy(s);out=apply_labels(s,rows);self.assertIn('DHCP (inferred)',out['wan']);self.assertIn('at test start',out['jobs'][0]['wan']);self.assertEqual(s,before)
 def test_stale(self):
  s,rows=self.session();s['elapsed']=20;self.assertEqual(apply_labels(s,rows)['wan'],'Unconfirmed');s['elapsed']=11;s['router_latest']={'ok':False,'t':11};self.assertEqual(apply_labels(s,rows)['wan'],'Unconfirmed')
 def test_marker(self):
  s,rows=self.session();s['markers']=[{'t':10}];self.assertEqual(apply_labels(s,rows)['wan'],'Unconfirmed')
 def test_job_time(self):
  s,rows=self.session();s['jobs'][0]['started']=100;self.assertEqual(apply_labels(s,rows)['jobs'][0]['wan'],'Unconfirmed at test start')
