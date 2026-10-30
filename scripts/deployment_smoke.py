"""Start an extracted release using clean dependencies and exercise real loopback HTTP."""
import argparse
import json
import socket
import sys
import threading
import time
import zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import uuid4


def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True);p.add_argument('--extract',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    target=Path(args.extract)
    if target.exists():raise RuntimeError('Clean deployment target already exists')
    target.mkdir(parents=True)
    with zipfile.ZipFile(args.archive) as archive:
        for name in archive.namelist():
            if not (target/name).resolve().is_relative_to(target.resolve()):raise RuntimeError('Unsafe archive path')
        archive.extractall(target)
    sys.path.insert(0,str(target))
    import httpx,uvicorn,importlib
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    config=(target/'.env.product.example').read_text(encoding='utf-8').replace('APP_URL=http://127.0.0.1:8215',f'APP_URL=http://127.0.0.1:{port}')
    (target/'.env').write_text(config,encoding='utf-8')
    app=importlib.import_module('main').app
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error',access_log=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    try:
        deadline=time.monotonic()+10
        while not server.started and time.monotonic()<deadline:time.sleep(.05)
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=10) as c:
            assert c.get('/api/ready').json()['ready']
            assert c.get('/api/purchases').json()['total']==0
            c.headers['x-scopepay-token']=c.get('/api/session').json()['token']
            for path,mime in [('/','text/html'),('/static/app.js','text/javascript'),('/static/style.css','text/css'),('/static/translations.js','text/javascript'),('/static/contracts.js','text/javascript')]:
                response=c.get(path);assert response.status_code==200 and mime in response.headers['content-type']
            ident=str(uuid4())
            body={'expected_version':0,'title':'Clean release smoke','supplier':'Synthetic supplier','source':'Provide a page.','currency':'USD','budget_cents':10000,'expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),'items':[{'title':'A page','quantity':1,'unit_cents':9900,'included':True,'evidence_quote':'Provide a page.'}]}
            assert c.put('/api/drafts/'+ident,json=body).status_code==200
            q=c.post('/api/drafts/'+ident+'/submit',json={}).json();base='/api/quotes/'+q['id']
            conf={'fingerprint':q['fingerprint'],'expected_currency':'USD','expected_total_cents':9900,'acknowledge_scope':True}
            for action,data in [('confirm',conf),('order',conf),('simulate-approval',{}),('capture',conf)]:
                r=c.post(base+'/'+action,json=data);assert r.status_code==200,(action,r.status_code)
            final=c.get(base+'/snapshot').json();assert final['receipt']['total_cents']==9900 and final['status']=='paid'
            exported=c.get(base+'/export');assert exported.json()['quote']['id']==q['id']
            report={'clean_extracted_source':str(target),'source_module':sys.modules['scopepay.app'].__file__,'entrypoint':sys.modules['main'].__file__,'configured_from_example':True,'initial_empty_workspace':True,'python':sys.executable,'actual_http_port':port,'state':'paid','receipt_cents':9900,'mode':'simulation','static_mime_checks':5,'public_deployment':False}
    finally:
        server.should_exit=True;thread.join(timeout=10);sock.close()
    if thread.is_alive():raise RuntimeError('Server did not shut down')
    report['server_stopped']=True;Path(args.output).write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))


if __name__=='__main__':main()
