"""Full purchase workflow and failure/restart invariants on either real backend."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import json

from fastapi.testclient import TestClient
from scopepay.app import create_app
from scopepay.core import packed, digest
from conftest import confirmation


def draft_body(**overrides):
    return dict(expected_version=0,title='Synthetic procurement',supplier='Synthetic studio',
        source='Build two pages.\nSupport excluded.',currency='USD',budget_cents=50000,
        expires_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
        notes='Two revisions included.',items=[dict(title='Two pages',quantity=2,unit_cents=12500,included=True,evidence_quote='Build two pages.'),
         dict(title='Support',quantity=1,unit_cents=0,included=False,evidence_quote='Support excluded.')], **overrides)


def submit(c):
    ident=str(uuid4());body=draft_body()
    assert c.put('/api/drafts/'+ident,json=body).status_code==200
    result=c.post('/api/drafts/'+ident+'/submit',json={})
    assert result.status_code==200,result.text
    return ident,result.json()


def approve(c,q):
    r=c.post('/api/quotes/'+q['id']+'/confirm',json={**confirmation(q),'reviewer':'Test reviewer','note':'Synthetic approval'})
    assert r.status_code==200,r.text


def test_budget_draft_conflict_and_submit_idempotency(factory):
    c=factory();ident=str(uuid4());body=draft_body();body['budget_cents']=100
    saved=c.put('/api/drafts/'+ident,json=body)
    assert saved.json()['version']==1
    assert c.put('/api/drafts/'+ident,json=body).json()['error']=='draft_changed_reload_before_save'
    assert c.post('/api/drafts/'+ident+'/submit',json={}).json()['error']=='quote_exceeds_budget'
    body.update(expected_version=1,budget_cents=50000)
    assert c.put('/api/drafts/'+ident,json=body).json()['version']==2
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:c.post('/api/drafts/'+ident+'/submit',json={}),range(4)))
    assert all(r.status_code==200 for r in results)
    assert len({r.json()['id'] for r in results})==1
    assert c.put('/api/drafts/'+ident,json={**body,'expected_version':2}).status_code==409
    q=results[0].json();assert q['total_cents']==25000 and q['excluded_items']==['Support']
    register=c.get('/api/purchases').json()
    assert register['total']==1 and register['items'][0]['status']=='review'


def test_saved_partial_draft_and_evidence_validation(factory):
    c=factory();ident=str(uuid4())
    assert c.put('/api/drafts/'+ident,json={'expected_version':0,'items':[{'title':'','unit_cents':0}]}).status_code==200
    assert c.post('/api/drafts/'+ident+'/submit',json={}).status_code==422
    body=draft_body();body['items'][0]['evidence_quote']='not in source'
    assert c.put('/api/drafts/'+str(uuid4()),json=body).json()['error']=='evidence_not_in_source'


def test_decline_revision_retains_original_and_one_active_revision(factory):
    c=factory();_,q=submit(c);base='/api/quotes/'+q['id']
    body={'fingerprint':q['fingerprint'],'reviewer':'Operator','note':'Need a smaller scope'}
    assert c.post(base+'/decline',json=body).status_code==200
    assert c.post(base+'/confirm',json=confirmation(q)).status_code==409
    with ThreadPoolExecutor(max_workers=3) as pool:
        revisions=list(pool.map(lambda _:c.post(base+'/revise',json={}).json(),range(3)))
    assert len({r['id'] for r in revisions})==1
    assert revisions[0]['parent_quote_id']==q['id']
    assert c.get(base).json()['fingerprint']==q['fingerprint']
    assert c.get(base+'/snapshot').json()['status']=='declined'


def test_expiry_blocks_order_and_capture_but_keeps_history(factory):
    c=factory();_,q=submit(c);approve(c,q);base='/api/quotes/'+q['id']
    assert c.post(base+'/order',json=confirmation(q)).status_code==200
    c.post(base+'/simulate-approval',json={})
    # Controlled clock fixture changes only a synthetic row; no real DB touched.
    with c.app.state.store.tx() as db:
        original=json.loads(db.execute('SELECT body FROM quotes WHERE id=?',(q['id'],)).fetchone()['body'])
        original['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        original.pop('fingerprint');original['fingerprint']=digest(original)
        db.execute('UPDATE quotes SET body=?,confirm_fingerprint=? WHERE id=?',(packed(original),original['fingerprint'],q['id']))
        c.app.state.store.index(db,q['id'],'quote',original,original['created_at'])
    q=c.get(base).json()
    for action in ('order','capture','confirm'):
        assert c.post(base+'/'+action,json=confirmation(q)).json()['error']=='approval_expired_use_revision'
    assert c.get(base+'/snapshot').json()['status']=='expired'
    assert c.post(base+'/revise',json={}).status_code==200


def test_loss_restart_reconcile_unique_receipt_and_no_recapture(factory):
    c=factory();_,q=submit(c);approve(c,q);base='/api/quotes/'+q['id']
    c.post(base+'/order',json={**confirmation(q),'simulation_scenario':'response_lost'})
    c.post(base+'/simulate-approval',json={})
    assert c.post(base+'/capture',json=confirmation(q)).status_code==504
    snapshot=c.get(base+'/snapshot').json();assert snapshot['status']=='unknown' and snapshot['receipt'] is None
    assert c.post(base+'/revoke',json=confirmation(q)).status_code==409
    assert c.post(base+'/revise',json={}).status_code==409
    assert c.post(base+'/capture',json=confirmation(q)).status_code==409
    with TestClient(create_app(c.app.state.settings)) as restarted:
        restarted.headers['x-scopepay-token']=restarted.get('/api/session').json()['token']
        assert restarted.get(base+'/snapshot').json()['status']=='unknown'
        for _ in range(3):assert restarted.post(base+'/refresh',json={}).status_code==200
        final=restarted.get(base+'/snapshot').json()
        assert final['status']=='paid' and final['receipt']['total_cents']==25000
        assert final['receipt']['payment_verified'] is False
        receipt=final['receipt']
        assert restarted.post(base+'/capture',json=confirmation(q)).status_code==200
        assert restarted.get(base+'/snapshot').json()['receipt']==receipt
    with c.app.state.store.tx(read=True) as db:
        assert db.execute('SELECT COUNT(*) AS n FROM receipts WHERE quote_id=?',(q['id'],)).fetchone()['n']==1
        assert db.execute('SELECT COUNT(*) AS n FROM simulated_captures WHERE quote_id=?',(q['id'],)).fetchone()['n']==1


def test_two_app_instances_concurrent_capture_have_one_receipt(factory):
    c=factory();_,q=submit(c);approve(c,q);base='/api/quotes/'+q['id']
    c.post(base+'/order',json=confirmation(q));c.post(base+'/simulate-approval',json={})
    with TestClient(create_app(c.app.state.settings)) as other:
        other.headers['x-scopepay-token']=other.get('/api/session').json()['token']
        with ThreadPoolExecutor(max_workers=6) as pool:
            responses=list(pool.map(lambda i:(c if i%2 else other).post(base+'/capture',json=confirmation(q)),range(6)))
        assert all(r.status_code==200 for r in responses)
    final=c.get(base+'/snapshot').json()
    assert [a['action'] for a in final['audit']].count('simulation_capture')==1
    assert final['receipt']['quote_id']==q['id']


def test_declined_processor_no_receipt_revision_allowed(factory):
    c=factory();_,q=submit(c);approve(c,q);base='/api/quotes/'+q['id']
    c.post(base+'/order',json={**confirmation(q),'simulation_scenario':'declined'});c.post(base+'/simulate-approval',json={})
    assert c.post(base+'/capture',json=confirmation(q)).status_code==409
    final=c.get(base+'/snapshot').json()
    assert final['status']=='payment_declined' and final['receipt'] is None
    assert c.post(base+'/revise',json={}).status_code==200


def test_export_source_binding_literal_search_and_bounds(factory):
    c=factory();_,q=submit(c);base='/api/quotes/'+q['id']
    export=c.get(base+'/export');assert export.json()['project']=='ScopePay'
    assert export.json()['quote']['id']==q['id'] and q['id'] in export.headers['content-disposition']
    assert c.get('/api/purchases',params={'search':'%'}).json()['total']==0
    assert c.get('/api/purchases',params={'search':"' OR 1=1--"}).json()['total']==0
    assert c.get('/api/purchases',params={'limit':101}).status_code==422
    assert c.get('/api/purchases',params={'offset':10001}).status_code==422


def test_secret_repr_and_model_backpressure(factory):
    c=factory(model_key='test-secret-model',client_secret='test-secret-payment',model='test')
    assert 'test-secret' not in repr(c.app.state.settings)
    c.app.state.model_slots.acquire()
    try:
        r=c.post('/api/analyses',json={'source':'Build a landing page.','mode':'model'})
        assert r.status_code==429 and r.headers['retry-after']=='2'
    finally:c.app.state.model_slots.release()


def test_reused_order_request_cannot_change_scenario(factory):
    c=factory();_,q=submit(c);approve(c,q);base='/api/quotes/'+q['id']
    assert c.post(base+'/order',json={**confirmation(q),'simulation_scenario':'response_lost'}).status_code==200
    result=c.post(base+'/order',json={**confirmation(q),'simulation_scenario':'normal'})
    assert result.status_code==409 and result.json()['error']=='idempotency_parameters_changed'


def test_foreign_client_is_rejected_even_with_local_host_header(factory):
    c=factory()
    with TestClient(c.app,client=('192.0.2.25',12345)) as remote:
        assert remote.get('/api/purchases').status_code==403


def test_corrupt_quote_cannot_be_approved_or_exported(factory):
    c=factory();_,q=submit(c);base='/api/quotes/'+q['id']
    with c.app.state.store.tx() as db:
        body=json.loads(db.execute('SELECT body FROM quotes WHERE id=?',(q['id'],)).fetchone()['body'])
        body['items'][0]['title']='Corrupted title'
        db.execute('UPDATE quotes SET body=? WHERE id=?',(packed(body),q['id']))
    assert c.get(base+'/export').json()['error']=='quote_integrity_mismatch'
    assert c.post(base+'/confirm',json=confirmation(q)).status_code==409


def test_corrupt_source_is_not_exported_as_grounded_evidence(factory):
    c=factory();_,q=submit(c)
    with c.app.state.store.tx() as db:
        body=json.loads(db.execute('SELECT body FROM analyses WHERE id=?',(q['analysis_id'],)).fetchone()['body'])
        body['source']='Altered source'
        db.execute('UPDATE analyses SET body=? WHERE id=?',(packed(body),q['analysis_id']))
    assert c.get('/api/quotes/'+q['id']+'/snapshot').json()['error']=='source_integrity_mismatch'
    assert c.post('/api/quotes/'+q['id']+'/confirm',json=confirmation(q)).json()['error']=='source_integrity_mismatch'


def test_broken_lock_connection_releases_local_capacity(factory,monkeypatch):
    c=factory();store=c.app.state.store
    class BrokenLockConnection:
        closed=False
        def execute(self,sql,params):
            if 'pg_try_advisory_lock' in sql:return self
            raise OSError('Synthetic lost connection during unlock')
        def fetchone(self):return {'locked':True}
        def close(self):self.closed=True
    connection=BrokenLockConnection()
    with monkeypatch.context() as patch:
        patch.setattr(store,'postgres',True)
        patch.setattr(store,'pool',None)
        patch.setattr(store,'connect',lambda:connection)
        with store.operation('test-cleanup'):pass
    assert connection.closed
    held=[]
    try:
        for _ in range(2):
            assert store.operation_slots.acquire(blocking=False)
            held.append(True)
        assert not store.operation_slots.acquire(blocking=False)
    finally:
        for _ in held:store.operation_slots.release()


def test_restore_rejects_unknown_columns_and_rolls_back(factory):
    from scripts.migrate_postgres import import_rows
    c=factory();store=c.app.state.store
    try:
        import_rows(store,{'analyses':[{'id':'restore-probe','body':'{}'}],
                           'quotes':[{'id':'probe','body':'{}','not_a_column':'bad'}]})
    except RuntimeError as exc:
        assert str(exc)=='Unsupported or inconsistent backup columns.'
    else:
        raise AssertionError('Malformed backup was accepted')
    with store.tx(read=True) as db:
        assert db.execute('SELECT COUNT(*) AS n FROM analyses').fetchone()['n']==0
