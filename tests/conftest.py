from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from scopepay.app import create_app
from scopepay.core import Settings


def pytest_addoption(parser):
    parser.addoption('--postgres-config', default=None, help='Private config; use isolated retained schemas in test_database')


@pytest.fixture
def factory(request):
    """Keep isolated test artifacts in-project; do not bulk-clean directories."""
    clients = []
    def make(**kwargs):
        model_transport = kwargs.pop('model_transport', None)
        payment_transport = kwargs.pop('payment_transport', None)
        path = Path(__file__).resolve().parent.parent / 'data' / 'test-runs' / (str(uuid4()) + '.db')
        pg_config=request.config.getoption('--postgres-config')
        if pg_config:
            import json
            import psycopg
            from urllib.parse import quote, urlencode
            cfg=json.loads(Path(pg_config).read_text(encoding='utf-8-sig'))
            schema='verify_'+uuid4().hex
            base=f"postgresql://{quote(cfg['username'],safe='')}:{quote(cfg['password'],safe='')}@{cfg['host']}:{cfg['port']}/{cfg['test_database']}"
            try:
                with psycopg.connect(base,connect_timeout=3) as conn:
                    conn.execute('CREATE SCHEMA '+schema)
            except Exception:
                raise RuntimeError('Test database unavailable; private config not logged') from None
            kwargs['database_url']=base+'?'+urlencode({'options':'-c search_path='+schema})
        app = create_app(Settings(db_path=str(path), **kwargs), model_transport, payment_transport)
        client = TestClient(app)
        client.headers['x-scopepay-token'] = client.get('/api/session').json()['token']
        clients.append(client)
        return client
    yield make
    for client in clients:
        client.close()
        client.app.state.store.close()


def quote(client, *, source='Design a landing page.\nWrite a handover guide.', quantity=3, unit_cents=101):
    analysis = client.post('/api/analyses', json={'source': source, 'mode': 'manual'})
    assert analysis.status_code == 200, analysis.text
    result = client.post('/api/quotes', json={'analysis_id': analysis.json()['id'], 'currency': 'USD',
        'items': [{'deliverable_id': 'd1', 'quantity': quantity, 'unit_cents': unit_cents}]})
    assert result.status_code == 200, result.text
    return result.json()


def confirmation(q):
    return {'fingerprint': q['fingerprint'], 'expected_currency': q['currency'],
            'expected_total_cents': q['total_cents'], 'acknowledge_scope': True}


def confirmed(client):
    q = quote(client)
    assert client.post(f"/api/quotes/{q['id']}/confirm", json=confirmation(q)).status_code == 200
    return q
