"""Real local API/SQLite tests. Provider cases explicitly use MockTransport."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import confirmation, confirmed, quote
from scopepay.app import create_app
from scopepay.core import Store
from test_paypal import setup, event, headers


@pytest.mark.parametrize('stage', ['confirmed', 'created', 'approved'])
def test_revoke_blocks_stale_actions_and_survives_restart(factory, stage):
    c = factory(); q = confirmed(c); base = f"/api/quotes/{q['id']}"
    if stage != 'confirmed':
        assert c.post(base + '/order', json=confirmation(q)).status_code == 200
    if stage == 'approved':
        assert c.post(base + '/simulate-approval', json={}).status_code == 200
    revoked = c.post(base + '/revoke', json=confirmation(q))
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()['revoked_at']
    assert revoked.json()['fingerprint'] == q['fingerprint']
    assert c.post(base + '/revoke', json=confirmation(q)).json() == revoked.json()
    # Rebuild the actual app/Store on the same database, not an in-memory flag.
    with TestClient(create_app(c.app.state.settings)) as restarted:
        restarted.headers['x-scopepay-token'] = restarted.get('/api/session').json()['token']
        assert restarted.get(base).json() == revoked.json()
        for action in ('confirm', 'order', 'simulate-approval', 'capture'):
            body = {} if action == 'simulate-approval' else confirmation(q)
            rejected = restarted.post(base + '/' + action, json=body)
            assert rejected.status_code == 409, (action, rejected.text)
            assert rejected.json()['error'] == 'quote_approval_revoked'
        if stage != 'confirmed':
            assert restarted.post(base + '/refresh', json={}).status_code == 200
        actions = [row['action'] for row in restarted.get(base + '/audit').json()]
        assert actions.count('human_approval_revoked') == 1
        assert 'simulation_capture' not in actions


def test_revoke_requires_exact_confirmed_quote(factory):
    c = factory(); q = quote(c); base = f"/api/quotes/{q['id']}"
    assert c.post(base + '/revoke', json=confirmation(q)).status_code == 409
    c.post(base + '/confirm', json=confirmation(q))
    bad = {**confirmation(q), 'expected_total_cents': q['total_cents'] + 1}
    assert c.post(base + '/revoke', json=bad).status_code == 409
    assert c.get(base).json().get('revoked_at') is None


def test_paid_quote_cannot_be_revoked_or_relabelled_unpaid(factory):
    c = factory(); q = confirmed(c); base = f"/api/quotes/{q['id']}"
    c.post(base + '/order', json=confirmation(q))
    c.post(base + '/simulate-approval', json={})
    paid = c.post(base + '/capture', json=confirmation(q)).json()
    r = c.post(base + '/revoke', json=confirmation(q))
    assert r.status_code == 409 and r.json()['error'] == 'payment_already_completed'
    assert c.get(base + '/order').json() == paid
    assert c.get(base).json()['revoked_at'] is None


def test_revocation_stops_provider_dispatch_and_webhooks_do_not_restore_approval(factory):
    c, fake, q, base = setup(factory)  # Explicit provider mock, real backend.
    c.post(base + '/order', json=confirmation(q)); fake.order['status'] = 'APPROVED'
    assert c.post(base + '/revoke', json=confirmation(q)).status_code == 200
    calls = (len(fake.creates), len(fake.captures), fake.gets)
    assert c.post(base + '/order', json=confirmation(q)).status_code == 409
    assert c.post(base + '/capture', json=confirmation(q)).status_code == 409
    assert (len(fake.creates), len(fake.captures), fake.gets) == calls
    received = c.post('/api/webhooks/paypal', json=event(), headers=headers())
    assert received.status_code == 200 and received.json()['reconciled'] is True
    assert c.post('/api/webhooks/paypal', json=event(), headers=headers()).json()['duplicate'] is True
    assert c.get(base).json()['revoked_at']
    assert c.get(base + '/order').json()['payment_verified'] is False
    assert c.post(base + '/capture', json=confirmation(q)).status_code == 409
    assert fake.captures == []
    # Revocation is local authority, not cancellation at PayPal. A payment
    # captured elsewhere must still be reported truthfully by reconciliation.
    fake.order['status'] = 'COMPLETED'
    fake.order['purchase_units'][0]['payments'] = {'captures': [{
        'id': 'EXTERNALCAPTURE', 'status': 'COMPLETED',
        'amount': fake.order['purchase_units'][0]['amount']}]}
    late = event(); late['id'] = 'WH-LATE-EXTERNAL'
    assert c.post('/api/webhooks/paypal', json=late, headers=headers()).status_code == 200
    assert c.get(base + '/order').json()['payment_verified'] is True
    assert c.get(base).json()['revoked_at']
    assert c.post(base + '/capture', json=confirmation(q)).status_code == 409
    assert fake.captures == []


def test_revoked_quote_never_creates_provider_order(factory):
    c, fake, q, base = setup(factory)
    assert c.post(base + '/revoke', json=confirmation(q)).status_code == 200
    assert c.post(base + '/order', json=confirmation(q)).status_code == 409
    assert c.post(base + '/capture', json=confirmation(q)).status_code == 409
    assert fake.oauth == 0 and fake.creates == [] and fake.captures == []


@pytest.mark.parametrize('remote_completed', [False, True])
def test_unknown_capture_cannot_claim_successful_revocation_after_restart(factory, remote_completed):
    c, fake, q, base = setup(factory)
    c.post(base + '/order', json=confirmation(q)); fake.order['status'] = 'APPROVED'
    def lost_response(request):
        if request.url.path.endswith('/capture'):
            if remote_completed:
                fake.handle(request)
            raise httpx.ReadTimeout('Deliberately unknown capture outcome: provider mock')
        return fake.handle(request)
    c.app.state.payments.adapter.transport = httpx.MockTransport(lost_response)
    assert c.post(base + '/capture', json=confirmation(q)).status_code == 504
    with TestClient(create_app(c.app.state.settings, payment_transport=httpx.MockTransport(fake.handle))) as restarted:
        restarted.headers['x-scopepay-token'] = restarted.get('/api/session').json()['token']
        rejected = restarted.post(base + '/revoke', json=confirmation(q))
        assert rejected.status_code == 409
        assert rejected.json()['error'] == 'capture_may_have_started_reconcile_first'
        assert restarted.get(base).json()['revoked_at'] is None
        refreshed = restarted.post(base + '/refresh', json={})
        assert refreshed.status_code == 200
        assert refreshed.json()['payment_verified'] is remote_completed
        # Even a currently APPROVED read cannot prove an in-flight capture failed.
        assert restarted.post(base + '/revoke', json=confirmation(q)).status_code == 409


def test_capture_inflight_and_revoke_are_serialized(factory):
    c, fake, q, base = setup(factory)
    c.post(base + '/order', json=confirmation(q)); fake.order['status'] = 'APPROVED'
    entered, release = Event(), Event()
    def controlled(request):
        if request.url.path.endswith('/capture'):
            entered.set()
            assert release.wait(5), 'test failed to release mock provider'
        return fake.handle(request)
    c.app.state.payments.adapter.transport = httpx.MockTransport(controlled)
    with ThreadPoolExecutor(max_workers=2) as pool:
        capture = pool.submit(c.post, base + '/capture', json=confirmation(q))
        try:
            assert entered.wait(5), 'capture did not reach provider'
            revoke = pool.submit(c.post, base + '/revoke', json=confirmation(q))
        finally:
            release.set()
        assert capture.result(timeout=5).status_code == 200
        assert revoke.result(timeout=5).status_code == 409
    assert len(fake.captures) == 1
    assert c.get(base).json()['revoked_at'] is None


def legacy_database():
    path = Path(__file__).resolve().parents[1] / 'data/test-runs' / (str(uuid4()) + '.db')
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE quotes(id TEXT PRIMARY KEY, body TEXT NOT NULL,
            confirmed_at TEXT, confirm_fingerprint TEXT);
            CREATE TABLE orders(quote_id TEXT PRIMARY KEY, mode TEXT NOT NULL,
            request_id TEXT NOT NULL, capture_request_id TEXT NOT NULL, started REAL NOT NULL,
            remote_id TEXT UNIQUE, status TEXT NOT NULL, body TEXT NOT NULL DEFAULT '{}');''')
        db.execute('INSERT INTO quotes VALUES(?,?,?,?)', ('legacy', '{"id":"legacy"}', 'old-time', 'old-fingerprint'))
        db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?)',
            ('legacy', 'sandbox', 'original-create', 'original-capture', 0, 'LEGACY123', 'APPROVED', '{}'))
    return path


def test_old_database_migration_preserves_history_and_unknown_capture_boundary():
    path = legacy_database()
    store = Store(str(path))
    with store.tx() as db:
        old = dict(db.execute('SELECT * FROM orders').fetchone())
        assert old['request_id'] == 'original-create' and old['capture_request_id'] == 'original-capture'
        assert old['capture_started_at'] == 'legacy-unknown'
        assert dict(db.execute('SELECT * FROM quotes').fetchone())['body'] == '{"id":"legacy"}'
    Store(str(path))  # Reopening migration must be idempotent.
    assert store.quote('legacy')['revoked_at'] is None


def test_failed_migration_rolls_back_columns_and_legacy_marking_together():
    path = legacy_database()
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TRIGGER fail_migration BEFORE UPDATE ON orders
                      BEGIN SELECT RAISE(ABORT, 'intentional migration failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='intentional migration failure'):
        Store(str(path))
    with sqlite3.connect(path) as db:
        assert 'capture_started_at' not in {r[1] for r in db.execute('PRAGMA table_info(orders)')}
        assert 'revoked_at' not in {r[1] for r in db.execute('PRAGMA table_info(quotes)')}
        assert db.execute('SELECT capture_request_id FROM orders').fetchone()[0] == 'original-capture'
