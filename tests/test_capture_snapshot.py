"""Local snapshot contract used after browser capture failure; provider is mocked."""
from fastapi.testclient import TestClient
import httpx

from conftest import confirmation
from scopepay.app import create_app
from test_paypal import setup


def test_failed_capture_snapshot_is_durable_without_provider_retry(factory):
    client, fake, quote, base = setup(factory)
    client.post(base + '/order', json=confirmation(quote))
    fake.order['status'] = 'APPROVED'
    fake.lose_capture = True
    failed = client.post(base + '/capture', json=confirmation(quote))
    assert failed.status_code == 504
    counts = (fake.gets, len(fake.captures))
    saved = client.get(base + '/order').json()
    assert saved['capture_started_at']
    assert saved['status'] == 'APPROVED' and saved['payment_verified'] is False
    assert (fake.gets, len(fake.captures)) == counts
    assert client.get(base).json()['fingerprint'] == quote['fingerprint']
    assert saved['total_cents'] == quote['total_cents'] == 303
    restarted = create_app(client.app.state.settings, payment_transport=httpx.MockTransport(fake.handle))
    with TestClient(restarted) as new_client:
        assert new_client.get(base + '/order').json() == saved
    assert (fake.gets, len(fake.captures)) == counts
    reconciled = client.post(base + '/refresh', json={}).json()
    assert reconciled['payment_verified'] is True
    assert len(fake.captures) == 1
