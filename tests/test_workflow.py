from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import confirmation, confirmed, quote
from scopepay.core import Settings


def test_full_simulation_and_duplicate_confirmation(factory):
    c = factory()
    q = quote(c)
    assert q['total_cents'] == 303 and q['total_display'] == '3.03'
    assert q['excluded_deliverable_ids'] == ['d2']
    base = f"/api/quotes/{q['id']}"
    assert c.post(base + '/order', json=confirmation(q)).status_code == 409
    first = c.post(base + '/confirm', json=confirmation(q)).json()
    assert c.post(base + '/confirm', json=confirmation(q)).json()['confirmed_at'] == first['confirmed_at']
    with ThreadPoolExecutor(max_workers=4) as pool:
        orders = list(pool.map(lambda _: c.post(base + '/order', json=confirmation(q)).json(), range(4)))
    assert len({o['order_id'] for o in orders}) == 1
    assert c.post(base + '/capture', json=confirmation(q)).status_code == 409
    c.post(base + '/simulate-approval', json={})
    paid = c.post(base + '/capture', json=confirmation(q)).json()
    assert paid['status'] == 'SIMULATED_PAID' and paid['payment_verified'] is False
    assert c.post(base + '/capture', json=confirmation(q)).json() == paid
    assert c.post(base + '/refresh', json={'status': 'PAID'}).status_code == 422
    actions = [x['action'] for x in c.get(base + '/audit').json()]
    assert actions.count('human_confirmed') == 1 and actions.count('simulation_order_created') == 1


@pytest.mark.parametrize('field,value', [('unit_cents', 1.01), ('unit_cents', -1), ('unit_cents', True),
    ('quantity', 0), ('quantity', '3'), ('quantity', 1001)])
def test_prices_require_bounded_exact_integers(factory, field, value):
    c = factory()
    a = c.post('/api/analyses', json={'source': 'Build a page', 'mode': 'manual'}).json()
    item = {'deliverable_id': 'd1', 'quantity': 1, 'unit_cents': 100, field: value}
    r = c.post('/api/quotes', json={'analysis_id': a['id'], 'currency': 'USD', 'items': [item]})
    assert r.status_code == 422


@pytest.mark.parametrize('change', [{'expected_currency': 'EUR'}, {'expected_total_cents': 304},
    {'fingerprint': '0' * 64}, {'acknowledge_scope': False}, {'status': 'PAID'}])
def test_confirmation_cannot_tamper_with_quote(factory, change):
    c = factory(); q = quote(c)
    r = c.post(f"/api/quotes/{q['id']}/confirm", json={**confirmation(q), **change})
    assert r.status_code in (409, 422)


def test_scope_and_currency_boundaries(factory):
    c = factory(); q = quote(c)
    body = {'analysis_id': q['analysis_id'], 'currency': 'USD', 'items': [
        {'deliverable_id': 'not-from-source', 'quantity': 1, 'unit_cents': 1}]}
    assert c.post('/api/quotes', json=body).json()['error'] == 'unknown_deliverable'
    body['items'][0]['deliverable_id'] = 'd1'; body['items'] *= 2
    assert c.post('/api/quotes', json=body).json()['error'] == 'duplicate_deliverable'
    body['items'] = body['items'][:1]; body['currency'] = 'JPY'
    assert c.post('/api/quotes', json=body).status_code == 422


def test_browser_boundary_and_input_limit(factory):
    c = factory()
    assert c.post('/api/analyses', json={'source': 'hello'}, headers={'x-scopepay-token': ''}).status_code == 403
    assert c.post('/api/analyses', json={'source': 'hello'}, headers={'origin': 'https://evil.example'}).status_code == 403
    assert c.post('/api/analyses', content='a'*65537, headers={'content-type': 'application/json'}).status_code == 413
    assert c.get('/api/health', headers={'host': 'evil.example'}).status_code == 400
    assert "frame-ancestors 'none'" in c.get('/').headers['content-security-policy']


def test_missing_sandbox_credentials_is_not_simulation_success(factory):
    c = factory(payment_mode='sandbox'); q = confirmed(c)
    r = c.post(f"/api/quotes/{q['id']}/order", json=confirmation(q))
    assert r.status_code == 503 and r.json()['error'] == 'sandbox_credentials_missing'


def test_no_production_or_plaintext_remote_model():
    with pytest.raises(ValueError):
        Settings(payment_mode='production')
    with pytest.raises(ValueError):
        Settings(model_base='http://untrusted.example/v1')


def test_static_mime_types_work_with_nosniff_on_windows(factory):
    c = factory()
    assert c.get('/static/style.css').headers['content-type'].startswith('text/css')
    assert c.get('/static/app.js').headers['content-type'].startswith('text/javascript')


def test_unrelated_inherited_provider_env_is_never_silently_used(monkeypatch):
    from pathlib import Path
    from uuid import uuid4
    import scopepay.core as core
    root = Path(__file__).resolve().parent.parent / 'data' / 'test-configs' / str(uuid4())
    root.mkdir(parents=True)
    monkeypatch.setattr(core, 'ROOT', root)
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://unrelated.example/v1')
    monkeypatch.setenv('OPENAI_API_KEY', 'fixture-unrelated-key')
    monkeypatch.delenv('SCOPEPAY_USE_PROCESS_ENV', raising=False)
    s = Settings.from_env()
    assert s.model_base == 'http://127.0.0.1:11435/v1' and s.model_key == 'local-not-a-secret'
    (root / '.env').write_text('OPENAI_BASE_URL=http://127.0.0.1:11435/v1\nOPENAI_API_KEY=project-placeholder\n', encoding='utf-8')
    monkeypatch.setenv('SCOPEPAY_USE_PROCESS_ENV', '1')
    assert Settings.from_env().model_key == 'project-placeholder'
