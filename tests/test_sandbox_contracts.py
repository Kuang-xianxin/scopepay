"""Provider responses are HTTP transport fixtures, NOT official Sandbox evidence."""
import json

import httpx
import pytest
from pathlib import Path
from uuid import uuid4

from conftest import confirmation, confirmed
from test_paypal import setup
from scopepay.core import Settings
from scopepay.preflight import check


def test_wrong_payee_cannot_dispatch_capture(factory):
    client, fake, quote, base = setup(factory)
    assert client.post(base + '/order', json=confirmation(quote)).status_code == 200
    fake.order['status'] = 'APPROVED'
    fake.order['purchase_units'][0]['payee'] = {'merchant_id': 'WRONGMERCHANT'}
    result = client.post(base + '/capture', json=confirmation(quote))
    assert result.status_code == 502
    assert result.json()['error'] == 'sandbox_payee_mismatch'
    assert not fake.captures
    assert client.get(base + '/snapshot').json()['receipt'] is None


def test_missing_merchant_blocks_order_before_network(factory):
    calls=[]
    client=factory(payment_mode='sandbox',client_id='fixture',client_secret='fixture',
                   payment_transport=httpx.MockTransport(lambda r:calls.append(r)))
    quote=confirmed(client)
    result=client.post('/api/quotes/'+quote['id']+'/order',json=confirmation(quote))
    assert result.status_code == 503
    assert result.json()['error'] == 'sandbox_merchant_id_missing'
    assert not calls


def test_payee_binding_and_unknown_recovery_keep_one_capture_and_receipt(factory):
    client, fake, quote, base=setup(factory)
    assert client.post(base+'/order',json=confirmation(quote)).status_code==200
    assert fake.order['purchase_units'][0]['payee']['merchant_id']=='TESTMERCHANT2'
    fake.order['status']='APPROVED';fake.lose_capture=True
    assert client.post(base+'/capture',json=confirmation(quote)).status_code==504
    assert client.get(base+'/snapshot').json()['status']=='unknown'
    assert client.post(base+'/refresh',json={}).json()['payment_verified'] is True
    first=client.get(base+'/snapshot').json()['receipt']
    assert client.post(base+'/capture',json=confirmation(quote)).status_code==200
    assert client.post(base+'/refresh',json={}).status_code==200
    assert client.get(base+'/snapshot').json()['receipt']==first
    assert len(fake.captures)==1
    assert fake.captures[0] != fake.creates[0]


@pytest.mark.parametrize('payee',[None,{},'not a payee',{'merchant_id':'OTHER'}])
def test_missing_or_mismatched_payee_never_becomes_receipt(factory,payee):
    client,fake,quote,base=setup(factory)
    client.post(base+'/order',json=confirmation(quote))
    fake.order['purchase_units'][0]['payee']=payee
    result=client.post(base+'/refresh',json={})
    assert result.status_code==502
    assert result.json()['error']=='sandbox_payee_mismatch'
    assert client.get(base+'/snapshot').json()['receipt'] is None


def configured():
    return Settings(payment_mode='sandbox',client_id='fixture-client',client_secret='fixture-secret',merchant_id='TESTMERCHANT2')


def test_offline_preflight_never_uses_transport_and_cannot_claim_sandbox_success():
    calls=[]
    transport=httpx.MockTransport(lambda r:calls.append(r))
    for settings,oauth in [(Settings(payment_mode='sandbox'),True),(configured(),False)]:
        report=check(settings,oauth=oauth,transport=transport)
        assert not report['oauth_verified'] and not report['checkout_verified']
        assert report['orders_created']==report['captures_requested']==0
    assert not calls


def test_oauth_preflight_only_requests_token_and_redacts_credentials():
    calls=[]
    def response(request):
        calls.append((request.method,str(request.url)))
        return httpx.Response(200,json={'access_token':'private-fixture-token','expires_in':3600})
    report=check(configured(),oauth=True,transport=httpx.MockTransport(response))
    assert calls==[('POST','https://api-m.sandbox.paypal.com/v1/oauth2/token')]
    assert report['oauth_verified'] and not report['checkout_verified']
    assert report['evidence']=='http_transport_fixture'
    assert not report['merchant_identity_verified']
    assert not any(secret in json.dumps(report) for secret in ('fixture-secret','fixture-client','private-fixture-token'))


@pytest.mark.parametrize('payload',[[],{}, {'access_token':'fixture','expires_in':True},
                                   {'access_token':'fixture','expires_in':0}])
def test_malformed_oauth_is_controlled_and_not_verified(payload):
    report=check(configured(),oauth=True,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload)))
    assert report['status']=='oauth_failed'
    assert report['error']=='sandbox_invalid_response'
    assert not report['oauth_verified']


def test_explicit_config_ignores_root_and_provider_environment(monkeypatch):
    # Keep this input, like all other isolated test artifacts.
    path=Path(__file__).resolve().parents[1]/'data'/'test-runs'/(uuid4().hex+'.env')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('PAYMENT_MODE=sandbox\nAPP_URL=http://127.0.0.1:18216\n',encoding='utf-8')
    monkeypatch.setenv('SCOPEPAY_USE_PROCESS_ENV','1')
    monkeypatch.setenv('PAYPAL_CLIENT_SECRET','inherited-do-not-use')
    monkeypatch.setenv('OPENAI_API_KEY','inherited-do-not-use')
    settings=Settings.from_env(path)
    assert settings.client_secret==''
    assert settings.model_key=='local-not-a-secret'
    assert settings.database_url=='' and settings.payment_mode=='sandbox'
    with pytest.raises(ValueError):Settings.from_env(path.with_suffix('.missing'))


def test_readiness_does_not_claim_provider_authentication(factory):
    client=factory(payment_mode='sandbox',client_id='fixture',client_secret='fixture',merchant_id='TESTMERCHANT2')
    result=client.get('/api/ready').json()
    assert result['ready'] and result['sandbox_configuration_complete']
    assert result['sandbox_ready'] is False
    assert result['sandbox_verification']=='not_probed_use_preflight'


def test_invalid_merchant_identifier_fails_before_any_network():
    with pytest.raises(ValueError):Settings(merchant_id='supplier-name')


def test_completed_without_capture_identity_is_not_paid(factory):
    client, fake, quote, base = setup(factory)
    assert client.post(base + '/order', json=confirmation(quote)).status_code == 200
    fake.order['status'] = 'COMPLETED'
    fake.order['purchase_units'][0]['payments'] = {'captures': [
        {'status': 'COMPLETED', 'amount': fake.order['purchase_units'][0]['amount']}]}
    result = client.post(base + '/refresh', json={})
    assert result.status_code == 200
    assert result.json()['payment_verified'] is False
    assert client.get(base + '/snapshot').json()['receipt'] is None
