"""Read-only adapter for the observed ZTE MC8500 ubus API.
Only authentication and allowlisted status requests are possible. No configuration writes.
"""
import hashlib
import http.client
import ipaddress
import json
import time

ZERO='0'*32
READS=[('zwrt_router.api','router_get_status',{}),('zte_nwinfo_api','nwinfo_get_netinfo',{}),('zwrt_data','get_wwaniface',{'source_module':'web','cid':1,'connect_status':''})]
METADATA=('uci','get',{'config':'zwrt_common_info','section':'common_config'})
class AuthError(Exception): pass

def digest(text):return hashlib.sha256(text.encode()).hexdigest().upper()

def interpret(wan,mobile,radio):
    active=wan.get('current_wan_interface','')
    cell=mobile.get('ipv4_dev_name','')
    wired=wan.get('mwan_wanlan1_wan_ifname','')
    connected=wan.get('current_wan_status') in ['ipv4_connected','ipv6_connected','ipv4_ipv6_connected']
    rat=radio.get('network_type','')
    label='Unknown'; evidence='The router did not provide an unambiguous active interface.'
    if connected and active and active==cell and mobile.get('connect_status') in ['ipv4_connected','ipv6_connected','ipv4_ipv6_connected']:
        label='Mobile / 5G NSA' if rat=='ENDC' else ('Mobile / '+rat if rat else 'Mobile')
        evidence='Active WAN interface matches the cellular interface reported by the router.'
    elif connected and active and wired and active==wired and active!=cell:
        label='Wired WAN';evidence='Active WAN interface matches the separately reported wired interface.'
    elif (connected and active == 'eth0.2' and cell and active != cell and not wired
          and wan.get('opms_wan_mode') == 'AUTO'
          and wan.get('opms_wan_auto_mode') == 'AUTO_DHCP'
          and wan.get('mwan_wanlan1_link_mode') == 'DHCP'
          and wan.get('mwan_wanlan1_status') in ['ipv4_connected','ipv4_ipv6_connected']):
        def valid_ip(value):
            try:
                ip=ipaddress.IPv4Address(value)
                return not(ip.is_unspecified or ip.is_loopback or ip.is_multicast or ip.is_link_local)
            except (ValueError,TypeError): return False
        address=wan.get('mwan_wanlan1_wan_ipaddr')
        mobile_address=mobile.get('ipv4_address')
        if valid_ip(address) and valid_ip(mobile_address) and address != mobile_address:
            label='Wired WAN - DHCP (inferred)'
            evidence='Auto DHCP is connected on eth0.2, separate from the cellular interface and address. The firmware leaves its wired-interface-name field empty; this is an inference, not proof of the upstream medium.'
    caveat=bool(wan.get('mwan_wanlan1_wan_ipaddr') and wan.get('mwan_wanlan1_wan_ipaddr')==mobile.get('ipv4_address') and not wired)
    return {'active_path':label,'path_evidence':evidence,'wan_fields_overlap':caveat}

class RouterClient:
    def __init__(self,host,source_ip,password_hash):
        address=ipaddress.IPv4Address(host)
        if not address.is_private or address.is_loopback:raise ValueError('Router address must be a private LAN IPv4 address')
        self.host=host;self.source_ip=source_ip;self.password_hash=password_hash;self.token=ZERO;self.metadata={};self.next_login=0
    def rpc(self,requests):
        allowed=READS+[METADATA,('zwrt_web','web_login_info',{})]
        for obj,method,args in requests:
            if (obj,method,args) not in allowed and not(obj=='zwrt_web' and method=='web_login' and set(args)=={'password'}):raise ValueError('Router request is not read-only or authentication')
        payload=[{'jsonrpc':'2.0','id':i+1,'method':'call','params':[self.token,obj,method,args]} for i,(obj,method,args) in enumerate(requests)]
        conn=http.client.HTTPConnection(self.host,80,timeout=2,source_address=(self.source_ip,0))
        try:
            conn.request('POST','/ubus/',json.dumps(payload),headers={'Content-Type':'application/json','Referer':f'http://{self.host}/','Z-Mode':'0','Z-Tag':requests[0][1]})
            response=conn.getresponse();raw=response.read(262145)
            if response.status!=200 or len(raw)>262144:raise ValueError('Router returned an invalid status response')
            data=json.loads(raw)
            if not isinstance(data,list) or len(data)!=len(requests):raise ValueError('Unexpected router response format')
            if not all(isinstance(x,dict) for x in data):raise ValueError('Malformed router response item')
            by_id={x.get('id'):x for x in data};out=[]
            for i in range(len(requests)):
                item=by_id.get(i+1,{})
                if not isinstance(item,dict):raise ValueError('Malformed router status response')
                result=item.get('result',[])
                if (item.get('error') or {}).get('code')==-32002 or (isinstance(result,list) and result and result[0]==6):raise AuthError('Router authentication expired')
                if not isinstance(result,list):raise ValueError('Malformed router status result')
                if len(result)!=2 or result[0]!=0 or not isinstance(result[1],dict):raise ValueError('Router status request unavailable')
                out.append(result[1])
            return out
        finally:conn.close()
    def login(self):
        if time.monotonic()<self.next_login:raise AuthError('Router login retry paused; verify credentials if failures continue')
        self.next_login=time.monotonic()+60
        info=self.rpc([('zwrt_web','web_login_info',{})])[0]
        salt=info.get('zte_web_sault')
        if not salt:raise AuthError('Router login challenge unavailable')
        if str(info.get('login_fail_lock_lefttime','0')) not in ['','0']:raise AuthError('Router login is temporarily locked')
        result=self.rpc([('zwrt_web','web_login',{'password':digest(self.password_hash+salt)})])[0]
        if str(result.get('result'))!='0' or not result.get('ubus_rpc_session'):raise AuthError('Router rejected the saved credential; update it in recording setup')
        self.token=result['ubus_rpc_session']
    def snapshot(self):
        start=time.monotonic()
        try:
            if self.token==ZERO:self.login()
            try:wan,radio,mobile=self.rpc(READS)
            except AuthError:
                self.token=ZERO
                raise
            if not self.metadata:
                try:
                    raw=self.rpc([METADATA])[0].get('values',{})
                    self.metadata={k:raw.get(k) for k in ['wa_inner_version','wa_module_version','integrate_version','hardware_version','model_name','device_market_name']}
                except (OSError,ValueError,AuthError):pass
            # These API methods contain network status only; do not query SIM identity, Wi-Fi keys or SMS.
            return {'ok':True,'at':time.time(),'latency_ms':round((time.monotonic()-start)*1000,2),'wan':wan,'radio':radio,'mobile':mobile,'device':self.metadata,**interpret(wan,mobile,radio)}
        except (OSError,ValueError,AuthError,http.client.HTTPException) as e:
            return {'ok':False,'at':time.time(),'latency_ms':round((time.monotonic()-start)*1000,2),'error':str(e)[:220],'active_path':'Unknown'}
