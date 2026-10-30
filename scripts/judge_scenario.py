"""Create retained synthetic purchases through real local HTTP; simulation only."""
import argparse
import json
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx


def run(url):
    parsed=urlparse(url)
    if (parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost')
            or parsed.username or parsed.password or parsed.path not in ('','/')
            or parsed.query or parsed.fragment):
        raise ValueError('Only a loopback HTTP origin is allowed')
    with httpx.Client(base_url=url,timeout=10,trust_env=False,follow_redirects=False) as client:
        assert client.get('/api/health').json()['payment_mode']=='simulation','Simulation is required; refusing financial calls'
        client.headers['x-scopepay-token']=client.get('/api/session').json()['token']
        def post(path,body,expected=200):
            response=client.post(path,json=body)
            assert response.status_code==expected,(path,response.status_code,response.text)
            return response.json()
        def purchase(label,seconds=86400):
            key=str(uuid4())
            source='Deliver two landing pages.\nDeliver a handover guide.\nHosting is excluded.'
            body={'expected_version':0,'title':'Synthetic: '+label,'supplier':'Synthetic design studio',
                  'source':source,'currency':'USD','budget_cents':35000,
                  'expires_at':(datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat(),
                  'items':[{'title':'Landing page','quantity':2,'unit_cents':12000,'included':True,'evidence_quote':'Deliver two landing pages.'},
                           {'title':'Handover guide','quantity':1,'unit_cents':6000,'included':True,'evidence_quote':'Deliver a handover guide.'},
                           {'title':'Hosting (excluded)','quantity':1,'unit_cents':0,'included':False,'evidence_quote':'Hosting is excluded.'}]}
            saved=client.put('/api/drafts/'+key,json=body);assert saved.status_code==200,saved.text
            quote=post('/api/drafts/'+key+'/submit',{})
            base='/api/quotes/'+quote['id']
            conf={'fingerprint':quote['fingerprint'],'expected_currency':'USD','expected_total_cents':30000,'acknowledge_scope':True}
            post(base+'/confirm',{**conf,'reviewer':'Synthetic judge walkthrough'})
            return base,conf

        base,conf=purchase('Recover one uncertain payment')
        mismatch=post(base+'/order',{**conf,'expected_total_cents':30100},409)
        post(base+'/order',{**conf,'simulation_scenario':'response_lost'})
        post(base+'/simulate-approval',{})
        lost=post(base+'/capture',conf,504)
        unknown=client.get(base+'/snapshot').json();assert unknown['status']=='unknown' and not unknown['receipt']
        post(base+'/refresh',{})
        paid=client.get(base+'/snapshot').json();assert paid['status']=='paid' and paid['receipt']['total_cents']==30000
        post(base+'/capture',conf)
        repeated=client.get(base+'/snapshot').json();assert repeated['receipt']==paid['receipt']
        exported=client.get(base+'/export').json();assert exported['receipt']==paid['receipt']
        revoked_base,revoked_conf=purchase('Revoke before capture')
        post(revoked_base+'/order',revoked_conf);post(revoked_base+'/simulate-approval',{})
        post(revoked_base+'/revoke',revoked_conf)
        revoked=post(revoked_base+'/capture',revoked_conf,409)
        expired_base,expired_conf=purchase('Approval has expired',seconds=4)
        post(expired_base+'/order',expired_conf);post(expired_base+'/simulate-approval',{})
        time.sleep(4.1)  # Wait for this synthetic approval, never change the system clock.
        expired=post(expired_base+'/capture',expired_conf,409)
        assert expired['error']=='approval_expired_use_revision'
        return {'evidence':'actual_loopback_http_local_simulation','source_kind':'manual_synthetic',
                'official_sandbox_verified':False,'model_called':False,'amount_cents':30000,
                'out_of_scope_payment_blocked':mismatch,'lost_response':lost,
                'unknown_before_reconciliation':unknown,'recovered':paid,'same_receipt_on_repeat':True,
                'revoke_blocked':revoked,'expiry_blocked':expired,'export_verified':True,
                'urls':{'paid':url+'/?quote='+paid['quote']['id'],
                        'revoked':url+'/?quote='+revoked_base.split('/')[3],
                        'expired':url+'/?quote='+expired_base.split('/')[3]}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:18216')
    parser.add_argument('--output',required=True)
    args=parser.parse_args();target=Path(args.output)
    if target.exists():raise SystemExit('Refusing to overwrite evidence')
    result=run(args.url)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x',encoding='utf-8') as output:json.dump(result,output,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k not in ('recovered','unknown_before_reconciliation')},ensure_ascii=False))
