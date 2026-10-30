"""Read configuration, optionally request OAuth. Never create/capture an order."""
import time

import httpx

from .core import Problem
from .payments import PayPal, SANDBOX


def check(settings, *, oauth=False, transport=None):
    report = {
        'payment_mode': settings.payment_mode,
        'endpoint': SANDBOX,
        'evidence': 'http_transport_fixture' if transport is not None else 'configuration_only',
        'checks': {'sandbox_mode': settings.payment_mode == 'sandbox',
                   'client_id_present': bool(settings.client_id),
                   'client_secret_present': bool(settings.client_secret),
                   'merchant_id_present': bool(settings.merchant_id)},
        'oauth_requested': oauth, 'oauth_verified': False,
        'merchant_identity_verified': False, 'checkout_verified': False,
        'orders_created': 0, 'captures_requested': 0,
    }
    report['configuration_complete'] = all(report['checks'].values())
    if not report['configuration_complete']:
        report['status'] = 'configuration_incomplete'
        return report
    if not oauth:
        report['status'] = 'configured_not_authenticated'
        return report
    adapter = PayPal(settings, transport)
    try:
        with httpx.Client(timeout=httpx.Timeout(8,connect=3,pool=2),transport=transport,
                          trust_env=False,follow_redirects=False) as client:
            adapter._oauth(client, time.monotonic()+20)
        report.update(status='oauth_authenticated_checkout_unverified',
                      oauth_verified=True,
                      evidence='http_transport_fixture' if transport is not None else 'official_sandbox_oauth')
    except Problem as exc:
        report.update(status='oauth_failed',error=exc.code)
    except httpx.TimeoutException:
        report.update(status='oauth_failed',error='sandbox_timeout')
    except httpx.HTTPError:
        report.update(status='oauth_failed',error='sandbox_unavailable')
    except (ValueError,KeyError,TypeError):
        report.update(status='oauth_failed',error='sandbox_invalid_response')
    return report
