"""Failure regressions. Provider responses are fixtures, never live payments."""
import json
import time
import pytest
import httpx
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from conftest import confirmation, confirmed
from test_paypal import setup
from scopepay.core import Problem,Settings,Store,digest,packed
from scopepay.payments import PayPal


def test_reconfirmation_cannot_change_approved_identity(factory):
    c=factory();q=confirmed(c)
    r=c.post('/api/quotes/'+q['id']+'/confirm',json={**confirmation(q),'reviewer':'Different reviewer'})
    assert r.status_code==409
    assert r.json()['error']=='approval_snapshot_mismatch'


def test_pending_remote_get_does_not_lock_read_or_revocation(factory):
    c,fake,q,base=setup(factory)
    assert c.post(base+'/order',json=confirmation(q)).status_code==200
    entered,release=Event(),Event()
    original=c.app.state.payments.adapter.get
    def waiting(order):
        entered.set();release.wait(4);return original(order)
    c.app.state.payments.adapter.get=waiting
    with ThreadPoolExecutor(max_workers=3) as pool:
        remote=pool.submit(c.post,base+'/refresh',json={})
        assert entered.wait(2)
        read=pool.submit(c.get,base+'/snapshot')
        revoke=pool.submit(c.post,base+'/revoke',json=confirmation(q))
        try:
            assert read.result(timeout=1).status_code==200
            assert revoke.result(timeout=1).status_code==200
        finally:release.set()
        assert remote.result(timeout=5).status_code==200
    assert c.get(base+'/snapshot').json()['status']=='revoked'


def test_lost_response_records_reconciliation_and_fixed_binding(factory):
    c=factory();q=confirmed(c);base='/api/quotes/'+q['id']
    c.post(base+'/order',json={**confirmation(q),'simulation_scenario':'response_lost'})
    c.post(base+'/simulate-approval',json={})
    assert c.post(base+'/capture',json=confirmation(q)).status_code==504
    snap=c.get(base+'/snapshot').json()
    assert snap['reconciliation']['state']=='pending'
    assert snap['reconciliation']['attempts']==0
    assert c.post(base+'/refresh',json={}).status_code==200
    assert c.get(base+'/snapshot').json()['reconciliation']['state']=='resolved'
    with c.app.state.store.tx(read=True) as db:
        row=db.execute('SELECT approval_snapshot FROM orders WHERE quote_id=?',(q['id'],)).fetchone()
        binding=json.loads(row['approval_snapshot'])
    assert binding['fingerprint']==q['fingerprint']
    assert binding['total_cents']==q['total_cents']


def test_reconciliation_attempts_and_backoff_survive_reopen(factory):
    c,fake,q,base=setup(factory)
    c.post(base+'/order',json=confirmation(q));fake.order['status']='APPROVED'
    def lost(*args):raise Problem('sandbox_timeout_retry_same_request',504)
    c.app.state.payments.adapter.capture=lost
    assert c.post(base+'/capture',json=confirmation(q)).status_code==504
    for attempt in range(5):
        with c.app.state.store.tx() as db:db.execute('UPDATE reconciliations SET next_attempt=0 WHERE quote_id=?',(q['id'],))
        assert c.post(base+'/refresh',json={}).status_code==200
        snap=c.get(base+'/snapshot').json()
        assert snap['reconciliation']['attempts']==attempt+1 and snap['status']=='unknown'
        assert c.post(base+'/refresh',json={}).status_code in (429,409)
    again=Store(c.app.state.settings.database_url or c.app.state.settings.db_path)
    try:
        with again.tx(read=True) as db:
            assert db.execute('SELECT state FROM reconciliations WHERE quote_id=?',(q['id'],)).fetchone()['state']=='manual'
    finally:again.close()
    assert not fake.captures


def test_abandoned_check_lease_recovers_but_never_recaptures(factory):
    c=factory();q=confirmed(c);base='/api/quotes/'+q['id']
    c.post(base+'/order',json={**confirmation(q),'simulation_scenario':'response_lost'});c.post(base+'/simulate-approval',json={})
    c.post(base+'/capture',json=confirmation(q))
    with c.app.state.store.tx() as db:
        db.execute('UPDATE orders SET reconcile_lease_until=?,reconcile_token=? WHERE quote_id=?',(time.time()+60,'dead-worker',q['id']))
        db.execute("UPDATE reconciliations SET state='checking',lease_token='dead-worker',attempts=1 WHERE quote_id=?",(q['id'],))
    assert c.post(base+'/refresh',json={}).status_code==409
    with c.app.state.store.tx() as db:db.execute('UPDATE orders SET reconcile_lease_until=0 WHERE quote_id=?',(q['id'],))
    assert c.post(base+'/refresh',json={}).status_code==200
    assert c.get(base+'/snapshot').json()['receipt']


def test_get_retries_are_bounded_capture_is_not_replayed():
    seen=[]
    def handler(request):
        seen.append(request.method)
        return httpx.Response(503,json={})
    adapter=PayPal(Settings(client_id='fixture',client_secret='fixture'),httpx.MockTransport(handler))
    adapter._token='fixture';adapter._expires=time.monotonic()+100
    with pytest.raises(Problem):adapter.get('ORDER123')
    assert seen==['GET','GET']
    seen.clear()
    with pytest.raises(Problem):adapter.capture('ORDER123','fixed-request')
    assert seen==['POST']


def test_auth_cache_singleflight_and_failure_cooldown():
    calls=[]
    def handler(request):
        if request.url.path.endswith('/token'):
            calls.append(1);time.sleep(.05)
            return httpx.Response(200,json={'access_token':'fixture','expires_in':3600})
        return httpx.Response(200,json={'id':'ORDER123'})
    adapter=PayPal(Settings(client_id='fixture',client_secret='fixture'),httpx.MockTransport(handler))
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda _:adapter.get('ORDER123'),range(8)))
    assert len(calls)==1
    adapter._token='';calls.clear()
    def broken(request):calls.append(1);return httpx.Response(503,json={})
    adapter.transport=httpx.MockTransport(broken)
    def attempt(_):
        try:adapter.get('ORDER123')
        except Problem:return True
    with ThreadPoolExecutor(max_workers=8) as pool:assert all(pool.map(attempt,range(8)))
    assert len(calls)==1


def test_oversized_upstream_is_rejected_before_decode():
    adapter=PayPal(Settings(client_id='fixture',client_secret='fixture'),httpx.MockTransport(lambda r:httpx.Response(200,content=b'x'*200000)))
    adapter._token='fixture';adapter._expires=time.monotonic()+100
    with pytest.raises(Problem) as exc:adapter.get('ORDER123')
    assert exc.value.code=='remote_response_too_large'


def test_corrupted_receipt_never_downloaded(factory):
    c=factory();q=confirmed(c);base='/api/quotes/'+q['id']
    for act,body in [('order',confirmation(q)),('simulate-approval',{}),('capture',confirmation(q))]:assert c.post(base+'/'+act,json=body).status_code==200
    with c.app.state.store.tx() as db:
        row=db.execute('SELECT body FROM receipts WHERE quote_id=?',(q['id'],)).fetchone()
        receipt=json.loads(row['body']);receipt['total_cents']+=1
        db.execute('UPDATE receipts SET body=? WHERE quote_id=?',(packed(receipt),q['id']))
    assert c.get(base+'/export').json()['error']=='receipt_integrity_mismatch'


def test_audit_pagination_and_export_do_not_silently_lose_history(factory):
    c=factory();q=confirmed(c);base='/api/quotes/'+q['id']
    with c.app.state.store.tx() as db:
        for n in range(205):c.app.state.store.audit(db,q['id'],'synthetic_check',{'n':n})
    snap=c.get(base+'/snapshot').json();assert len(snap['audit'])==200 and snap['audit_truncated']
    prior=c.get(base+'/audit',params={'before':snap['audit'][0]['seq']}).json()
    full=c.get(base+'/export').json();assert not full['audit_truncated']
    assert prior+snap['audit']==full['audit']


def test_sync_capacity_counts_real_work_after_caller_disappears():
    from scopepay.execution import bounded_routes
    metrics={};route=bounded_routes(metrics,limit=1)
    entered,release=Event(),Event()
    def slow():entered.set();release.wait(3);return True
    wrapped=route('/api/test',slow).endpoint
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending=pool.submit(wrapped);assert entered.wait(1)
        # Client cancellation cannot stop a Python thread; it must still consume capacity.
        pending.cancel()
        with pytest.raises(Problem):wrapped()
        assert metrics['work_active']==1 and metrics['work_rejected']==1
        release.set();assert pending.result(timeout=2)
    assert metrics['work_active']==0


def test_create_cleanup_failure_preserves_remote_unknown(factory,monkeypatch):
    from contextlib import contextmanager
    c,fake,q,base=setup(factory);store=c.app.state.store;original=store.tx
    @contextmanager
    def broken_cleanup(*args,**kwargs):
        with original(*args,**kwargs) as db:
            execute=db.execute
            def observed(sql,params=()):
                if sql.startswith('UPDATE orders SET create_lease_until=0'):raise Problem('synthetic_cleanup_failure',503)
                return execute(sql,params)
            db.execute=observed;yield db
    monkeypatch.setattr(store,'tx',broken_cleanup)
    fake.lose_create=True
    assert c.post(base+'/order',json=confirmation(q)).json()['error']=='sandbox_timeout_retry_same_request'


@pytest.mark.parametrize('corrupt',[{'links':[3]},{'links':[{'rel':'approve','href':'https://www.sandbox.paypal.com:bad/'}]},{'status':[]}])
def test_invalid_remote_shape_is_controlled(factory,corrupt):
    c,fake,q,base=setup(factory)
    assert c.post(base+'/order',json=confirmation(q)).status_code==200
    fake.order.update(corrupt)
    assert c.post(base+'/refresh',json={}).status_code==502
