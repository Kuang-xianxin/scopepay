"""Regression from the 2026-10-28 official Sandbox GET shape.

These automated responses remain fixtures, not additional provider calls.
"""
from conftest import confirmation
from test_paypal import setup
import httpx


def test_official_amount_breakdown_metadata_preserves_verified_flow(factory):
    client, fake, quote, base = setup(factory)
    # The provider's real GET added an empty breakdown to the monetary object.
    # Keep the fixture's lifecycle, but add the observed optional metadata.
    original_handler = fake.handle

    def decorated(request):
        response = original_handler(request)
        if request.method == 'GET' and '/v2/checkout/orders/' in str(request.url):
            data = response.json()
            data['purchase_units'][0]['amount']['breakdown'] = {}
            for capture in data['purchase_units'][0].get('payments', {}).get('captures', []):
                capture['amount']['breakdown'] = {}
            return httpx.Response(response.status_code, json=data)
        return response

    client.app.state.payments.adapter.transport = httpx.MockTransport(decorated)
    result = client.post(base + '/order', json=confirmation(quote))
    assert result.status_code == 200
    fake.order['status'] = 'APPROVED'
    assert client.post(base + '/capture', json=confirmation(quote)).json()['payment_verified'] is True
    receipt = client.get(base + '/snapshot').json()['receipt']
    assert receipt is not None
    fake.order['purchase_units'][0]['amount']['value'] = '999.00'
    assert client.post(base + '/refresh', json={}).status_code == 502
