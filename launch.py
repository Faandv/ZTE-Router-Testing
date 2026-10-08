#!/usr/bin/env python3
import json
import threading
import urllib.request
import webbrowser
import time
import server
url=f'http://127.0.0.1:{server.PORT}'
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(url+'/api/config',timeout=2) as r: existing=json.load(r)
    if existing.get('app')=='Router Lab':
        webbrowser.open(url)
        raise SystemExit(0)
except (OSError,ValueError): pass

def open_when_ready():
    for _ in range(30):
        try:
            with opener.open(url,timeout=1) as r:
                if r.status==200: webbrowser.open(url);return
        except OSError: time.sleep(.2)
threading.Thread(target=open_when_ready,daemon=True).start()
server.main()
