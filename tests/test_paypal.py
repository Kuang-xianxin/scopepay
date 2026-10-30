import json
import time

import httpx
import pytest

from conftest import confirmation, confirmed
from scopepay.core import Settings
from scopepay.payments import Payments, PayPal, RETRY_WINDOW_SECONDS, SANDBOX


class SandboxFixture:
    """Protocol fixture, NOT a live PayPal Sandbox connection."""
    def __init__(self):
        self.creates = []; self.captures = []; self.gets = 0; self.oauth = 0
        self.order = None; self.signature = 'SUCCESS'; self.verify_bodies = []
        self.lose_create = False; self.lose_capture = False; self.amount_override = None
        self.approval_host = 'www.sandbox.paypal.com'
        self.once_401 = False

    def handle(self, request):
        assert str(request.url).startswith(SANDBOX + '/')
        path = request.url.path
        if path == '/v1/oauth2/token':
            self.oauth += 1
            assert request.headers['authorization'].startswith('Basic ')
            assert request.content == b'grant_type=client_credentials'
            return httpx.Response(200, json={'access_token': 'test-only-token', 'expires_in': 3600})
        assert request.headers['authorization'] == 'Bearer test-only-token'
        if self.once_401:
            self.once_401 = False
            return httpx.Response(401, json={})
        if path == '/v1/notifications/verify-webhook-signature':
            self.verify_bodies.append(json.loads(request.content))
            return httpx.Response(200, json={'verification_status': self.signature})
        if path == '/v2/checkout/orders':
            self.creates.append(request.headers['paypal-request-id'])
            body = json.loads(request.content)
            assert body['intent'] == 'CAPTURE' and 'card' not in body['payment_source']
            if not self.order:
                self.order = {'id': 'TESTORDER123', 'status': 'PAYER_ACTION_REQUIRED',
                              'purchase_units': body['purchase_units'],
                              'links': [{'rel': 'payer-action', 'href': f'https://{self.approval_host}/checkoutnow?token=TESTORDER123'}]}
            if self.lose_create:
                self.lose_create = False
                raise httpx.ReadTimeout('response lost after acceptance')
            return httpx.Response(201, json=self.order)
        if path.endswith('/capture'):
            self.captures.append(request.headers['paypal-request-id'])
            self.order['status'] = 'COMPLETED'
            self.order['purchase_units'][0]['payments'] = {'captures': [{'id': 'CAPTURE123',
                'status': 'COMPLETED', 'amount': self.order['purchase_units'][0]['amount']}]}
            if self.lose_capture:
                self.lose_capture = False
                raise httpx.ReadTimeout('capture accepted but response lost')
            return httpx.Response(201, json=self.order)
        if request.method == 'GET':
            self.gets += 1
            result = json.loads(json.dumps(self.order))
            if self.amount_override:
                result['purchase_units'][0]['amount']['value'] = self.amount_override
            return httpx.Response(200, json=result)
        raise AssertionError((request.method, path))


def setup(factory):
    fake = SandboxFixture()
    c = factory(payment_mode='sandbox', client_id='fixture-client', client_secret='fixture-secret',
                merchant_id='TESTMERCHANT2',
                webhook_id='WHCONFIG123', payment_transport=httpx.MockTransport(fake.handle))
    q = confirmed(c)
    return c, fake, q, f"/api/quotes/{q['id']}"


def headers():
    return {'paypal-auth-algo': 'SHA256withRSA',
            'paypal-cert-url': SANDBOX + '/v1/notifications/certs/CERT-TEST',
            'paypal-transmission-id': 'T-123', 'paypal-transmission-sig': 'fixture-signature',
            'paypal-transmission-time': '2026-10-22T15:00:00Z'}


def event():
    return {'id': 'WH-EVENT123', 'event_type': 'PAYMENT.CAPTURE.COMPLETED', 'resource': {
        'status': 'COMPLETED', 'amount': {'value': '99999.00', 'currency_code': 'USD'},
        'supplementary_data': {'related_ids': {'order_id': 'TESTORDER123'}}}}


def test_sandbox_protocol_and_server_verified_capture(factory):
    c, fake, q, base = setup(factory)
    fake.once_401 = True
    order = c.post(base + '/order', json=confirmation(q))
    assert order.status_code == 200, order.text
    assert fake.oauth == 2 and fake.gets == 1
    assert c.post(base + '/simulate-approval', json={}).status_code == 403
    assert c.post(base + '/capture', json=confirmation(q)).status_code == 409
    fake.order['status'] = 'APPROVED'
    paid = c.post(base + '/capture', json=confirmation(q))
    assert paid.json()['status'] == 'SANDBOX_PAID' and paid.json()['payment_verified'] is True
    assert fake.captures[0] != fake.creates[0]
    c.post(base + '/capture', json=confirmation(q))
    assert len(fake.captures) == 1


def test_uncertain_create_reuses_persisted_id_after_restart(factory):
    c, fake, q, base = setup(factory); fake.lose_create = True
    assert c.post(base + '/order', json=confirmation(q)).status_code == 504
    s = c.app.state.settings
    restarted = Payments(c.app.state.store, s, PayPal(s, httpx.MockTransport(fake.handle)))
    result = restarted.create(q['id'])
    assert result['order_id'] == 'TESTORDER123'
    assert len(fake.creates) == 2 and len(set(fake.creates)) == 1


def test_uncertain_capture_recovers_from_server_without_recapture(factory):
    c, fake, q, base = setup(factory)
    c.post(base + '/order', json=confirmation(q)); fake.order['status'] = 'APPROVED'; fake.lose_capture = True
    assert c.post(base + '/capture', json=confirmation(q)).status_code == 504
    assert c.post(base + '/capture', json=confirmation(q)).json()['payment_verified'] is True
    assert len(fake.captures) == 1


def test_uncertain_order_expires_without_new_remote_create(factory):
    c, fake, q, base = setup(factory); fake.lose_create = True
    c.post(base + '/order', json=confirmation(q))
    with c.app.state.store.tx() as db:
        db.execute('UPDATE orders SET started=?', (time.time() - RETRY_WINDOW_SECONDS - 1,))
    assert c.post(base + '/order', json=confirmation(q)).status_code == 409
    assert len(fake.creates) == 1


def test_server_amount_mismatch_blocks_capture(factory):
    c, fake, q, base = setup(factory)
    c.post(base + '/order', json=confirmation(q)); fake.order['status'] = 'APPROVED'; fake.amount_override = '9.99'
    r = c.post(base + '/capture', json=confirmation(q))
    assert r.status_code == 502 and not fake.captures


def test_production_approval_link_is_rejected(factory):
    c, fake, q, base = setup(factory); fake.approval_host = 'www.paypal.com'
    r = c.post(base + '/order', json=confirmation(q))
    assert r.status_code == 502 and r.json()['error'] == 'approval_url_not_sandbox'


def test_webhook_signature_dedup_and_status_refetch(factory):
    c, fake, q, base = setup(factory)
    c.post(base + '/order', json=confirmation(q))
    fake.signature = 'FAILURE'
    assert c.post('/api/webhooks/paypal', json=event(), headers=headers()).status_code == 401
    assert c.get(base + '/order').json()['status'] == 'PAYER_ACTION_REQUIRED'
    fake.signature = 'SUCCESS'
    r = c.post('/api/webhooks/paypal', json=event(), headers=headers())
    assert r.json()['reconciled'] is True
    # Signed event claims paid, but the server GET says buyer action is required.
    assert c.get(base + '/order').json()['payment_verified'] is False
    assert fake.verify_bodies[-1]['webhook_id'] == 'WHCONFIG123'
    assert fake.verify_bodies[-1]['webhook_event'] == event()
    count = fake.gets
    assert c.post('/api/webhooks/paypal', json=event(), headers=headers()).json()['duplicate'] is True
    assert fake.gets == count


def test_webhook_cert_ssrf_and_missing_headers(factory):
    c, fake, q, base = setup(factory)
    assert c.post('/api/webhooks/paypal', json=event()).status_code == 400
    bad = {**headers(), 'paypal-cert-url': 'http://127.0.0.1/private'}
    assert c.post('/api/webhooks/paypal', json=event(), headers=bad).status_code == 400
    assert not fake.verify_bodies


def test_simulation_does_not_accept_paypal_webhooks(factory):
    c = factory()
    assert c.post('/api/webhooks/paypal', json=event(), headers=headers()).status_code == 409


def test_bad_signed_event_structure_cannot_change_payment(factory):
    c, fake, q, base = setup(factory)
    c.post(base + '/order', json=confirmation(q))
    malformed = event(); malformed['resource']['supplementary_data'] = 'untrusted text'
    r = c.post('/api/webhooks/paypal', json=malformed, headers=headers())
    assert r.status_code == 200 and r.json()['reconciled'] is False
    assert c.get(base + '/order').json()['payment_verified'] is False


def test_completed_order_without_capture_is_not_paid(factory):
    c, fake, q, base = setup(factory)
    c.post(base + '/order', json=confirmation(q)); fake.order['status'] = 'COMPLETED'
    r = c.post(base + '/refresh', json={})
    assert r.json()['status'] == 'REVIEW_REQUIRED' and r.json()['payment_verified'] is False
