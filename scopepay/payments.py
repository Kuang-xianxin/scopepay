"""Sandbox-only HTTP adapter. Tests replace transport, never the endpoint policy."""
import json
import re
import threading
import time
from urllib.parse import urlparse

import httpx
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_random_exponential

from .core import Problem, money, new_id, now, packed
from .workspace import active
from .remote import bounded_response

SANDBOX = 'https://api-m.sandbox.paypal.com'
# Conservatively stop uncertain retries before PayPal's default 6-hour retention.
RETRY_WINDOW_SECONDS = 5 * 60 * 60


class PayPal:
    def __init__(self, settings, transport=None):
        self.s, self.transport = settings, transport
        self._token = ''
        self._expires = 0
        self._lock = threading.Lock()
        self._cooldown = 0

    @property
    def configured(self):
        return bool(self.s.client_id and self.s.client_secret)

    def _oauth(self, client, budget_end):
        if not self.configured:
            raise Problem('sandbox_credentials_missing', 503)
        if not self._lock.acquire(timeout=2):
            raise Problem('sandbox_auth_temporarily_unavailable',503)
        try:
            if self._token and time.monotonic() < self._expires:
                return self._token
            if time.monotonic()<self._cooldown:
                raise Problem('sandbox_auth_temporarily_unavailable',503)
            try:
                response = bounded_response(client,'POST',SANDBOX + '/v1/oauth2/token',limit=16384,deadline=max(.1,budget_end-time.monotonic()),
                    auth=(self.s.client_id, self.s.client_secret),
                    data={'grant_type': 'client_credentials'}, headers={'Accept': 'application/json'})
                self._check(response)
                body = response.json()
                if not isinstance(body,dict):
                    raise Problem('sandbox_invalid_response',502)
                if not isinstance(body.get('access_token'),str) or not body['access_token'] or len(body['access_token'])>8192:
                    raise Problem('sandbox_invalid_response',502)
                if type(body.get('expires_in')) is not int or body['expires_in'] <= 60:
                    raise Problem('sandbox_invalid_response',502)
                self._token = body['access_token']
                self._expires = time.monotonic() + max(0, min(3600,int(body['expires_in'])) - 60)
            except Exception:
                self._cooldown=time.monotonic()+3
                raise
            return self._token
        finally:self._lock.release()

    @staticmethod
    def _check(response):
        if response.status_code >= 300:
            # Do not expose credentials, buyer data, or upstream response bodies.
            raise Problem('sandbox_http_' + str(response.status_code), 502)

    def request(self, method, path, body=None, request_id=None):
        # Only observations are automatically retried. A capture is never replayed.
        attempts=2 if method=='GET' else 1
        budget_end=time.monotonic()+20
        retryable=lambda e:isinstance(e,Problem) and e.code in (
            'sandbox_timeout_retry_same_request','sandbox_unavailable','sandbox_http_502','sandbox_http_503','sandbox_http_504')
        for attempt in Retrying(stop=stop_after_attempt(attempts),wait=wait_random_exponential(multiplier=.1,max=.4),
                                retry=retry_if_exception(retryable),reraise=True):
            with attempt:return self._request_once(method,path,body,request_id,budget_end)

    def _request_once(self, method, path, body=None, request_id=None, budget_end=None):
        if not path.startswith(('/v1/notifications/', '/v2/checkout/orders')):
            raise Problem('sandbox_path_forbidden', 400)
        try:
            with httpx.Client(timeout=httpx.Timeout(8,connect=3,pool=2), transport=self.transport, trust_env=False,
                              follow_redirects=False) as client:
                for attempt in range(2):
                    if time.monotonic()>=budget_end:raise Problem('sandbox_timeout_retry_same_request',504)
                    headers = {'Authorization': 'Bearer ' + self._oauth(client,budget_end),
                               'Content-Type': 'application/json', 'Prefer': 'return=representation'}
                    if request_id:
                        headers['PayPal-Request-Id'] = request_id
                    if time.monotonic()>=budget_end:raise Problem('sandbox_timeout_retry_same_request',504)
                    response = bounded_response(client,method,SANDBOX + path,json=body,headers=headers,deadline=budget_end-time.monotonic())
                    if response.status_code == 401 and attempt == 0:
                        self._token = ''
                        continue
                    self._check(response)
                    value = response.json()
                    if not isinstance(value, dict):
                        raise Problem('sandbox_invalid_response', 502)
                    return value
        except httpx.TimeoutException as exc:
            raise Problem('sandbox_timeout_retry_same_request', 504) from exc
        except httpx.HTTPError as exc:
            raise Problem('sandbox_unavailable', 502) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise Problem('sandbox_invalid_response', 502) from exc

    def create(self, quote, request_id):
        if not self.s.merchant_id:
            raise Problem('sandbox_merchant_id_missing',503)
        return self.request('POST', '/v2/checkout/orders', {
            'intent': 'CAPTURE',
            'purchase_units': [{'reference_id': quote['id'], 'custom_id': quote['id'],
                'payee': {'merchant_id': self.s.merchant_id},
                'description': 'ScopePay human-confirmed service scope',
                'amount': {'currency_code': quote['currency'], 'value': money(quote['total_cents'])}}],
            'payment_source': {'paypal': {'experience_context': {
                'shipping_preference': 'NO_SHIPPING', 'user_action': 'PAY_NOW',
                'return_url': self.s.app_url + '/?quote=' + quote['id'] + '&checkout=returned',
                'cancel_url': self.s.app_url + '/?quote=' + quote['id'] + '&checkout=cancelled',
            }}},
        }, request_id)

    @staticmethod
    def order_path(order_id):
        if not isinstance(order_id, str) or not re.fullmatch(r'[A-Z0-9]{1,36}', order_id):
            raise Problem('invalid_sandbox_order_id', 502)
        return '/v2/checkout/orders/' + order_id

    def get(self, order_id):
        return self.request('GET', self.order_path(order_id))

    def capture(self, order_id, request_id):
        return self.request('POST', self.order_path(order_id) + '/capture', {}, request_id)

    def verify(self, headers, event):
        if not self.s.webhook_id:
            raise Problem('sandbox_webhook_id_missing', 503)
        names = ('auth-algo', 'cert-url', 'transmission-id', 'transmission-sig', 'transmission-time')
        values = {name.replace('-', '_'): headers.get('paypal-' + name, '') for name in names}
        if any(not v or len(v) > 1500 for v in values.values()):
            raise Problem('webhook_signature_headers_missing', 400)
        try:
            cert = urlparse(values['cert_url'])
            cert_port = cert.port
        except ValueError as exc:
            raise Problem('webhook_certificate_not_sandbox', 400) from exc
        if (cert.scheme != 'https' or cert.hostname not in ('api.sandbox.paypal.com', 'api-m.sandbox.paypal.com')
                or cert.username or cert.password or cert_port not in (None, 443)
                or not cert.path.startswith('/v1/notifications/certs/') or cert.query or cert.fragment):
            raise Problem('webhook_certificate_not_sandbox', 400)
        result = self.request('POST', '/v1/notifications/verify-webhook-signature',
            {**values, 'webhook_id': self.s.webhook_id, 'webhook_event': event})
        if result.get('verification_status') != 'SUCCESS':
            raise Problem('webhook_signature_invalid', 401)


def verified_summary(raw, quote, expected_id, merchant_id):
    """Payment state comes from a server GET, bound to quote ID AND exact amount."""
    expected = {'currency_code': quote['currency'], 'value': money(quote['total_cents'])}
    def amount_matches(amount):
        # Official GET responses may add optional metadata such as breakdown.
        # Verify the monetary identity, not equality of the whole JSON object.
        return (isinstance(amount, dict)
                and amount.get('currency_code') == expected['currency_code']
                and amount.get('value') == expected['value'])
    if raw.get('id') != expected_id:
        raise Problem('sandbox_order_identity_mismatch', 502)
    units = raw.get('purchase_units', [])
    if (not isinstance(units, list) or len(units) != 1 or not isinstance(units[0], dict)
            or units[0].get('custom_id') != quote['id'] or not amount_matches(units[0].get('amount'))):
        raise Problem('sandbox_order_amount_or_scope_mismatch', 502)
    unit = units[0]
    if (not merchant_id or not isinstance(unit.get('payee'),dict)
            or unit['payee'].get('merchant_id') != merchant_id):
        raise Problem('sandbox_payee_mismatch',502)
    status = raw.get('status', 'UNKNOWN')
    if not isinstance(status,str) or len(status)>40:
        raise Problem('sandbox_invalid_response',502)
    payment_data = unit.get('payments') or {}
    if not isinstance(payment_data, dict):
        raise Problem('sandbox_invalid_response', 502)
    captures = payment_data.get('captures') or []
    paid = (status == 'COMPLETED' and isinstance(captures, list) and len(captures) == 1
            and isinstance(captures[0], dict)
            and isinstance(captures[0].get('id'),str)
            and re.fullmatch(r'[A-Z0-9]{1,36}',captures[0]['id'])
            and captures[0].get('status') == 'COMPLETED' and amount_matches(captures[0].get('amount'))
            and not payment_data.get('refunds'))
    approval_url = None
    links=raw.get('links',[])
    if not isinstance(links,list) or any(not isinstance(x,dict) for x in links):
        raise Problem('sandbox_invalid_response',502)
    for link in links:
        if link.get('rel') in ('approve', 'payer-action'):
            try:
                if not isinstance(link.get('href'),str):raise ValueError()
                url = urlparse(link['href']);port=url.port
            except ValueError:raise Problem('approval_url_not_sandbox',502) from None
            if (url.scheme != 'https' or url.hostname != 'www.sandbox.paypal.com'
                    or url.username or url.password or port not in (None, 443)):
                raise Problem('approval_url_not_sandbox', 502)
            approval_url = link['href']
    return {'remote_status': status, 'status': 'SANDBOX_PAID' if paid else (
            'REVIEW_REQUIRED' if status == 'COMPLETED' else status),
            'payment_verified': bool(paid), 'approval_url': approval_url,
            'verified_at': now(), 'evidence': 'PayPal Sandbox server GET',
            'currency': quote['currency'], 'total_cents': quote['total_cents']}


class Payments:
    def __init__(self, store, settings, adapter):
        self.store, self.s, self.adapter = store, settings, adapter
        # Cross-process reservation happens in Store; network calls hold no DB lock.

    def _row(self, key):
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM orders WHERE quote_id=?', (key,)).fetchone()
        if not row:
            raise Problem('order_not_created', 409)
        if row['mode'] != self.s.payment_mode:
            raise Problem('order_mode_changed_use_new_quote', 409)
        return dict(row)

    def view(self, key):
        row = self._row(key)
        return dict(quote_id=key, mode=row['mode'], order_id=row['remote_id'],
                    capture_started_at=row['capture_started_at'],
                    **{**json.loads(row['body']), 'status': row['status']})

    def require_active_approval(self, key):
        quote = self.store.quote(key)
        active(quote)
        return quote

    def binding(self,quote):
        return {k:quote.get(k) for k in ('id','fingerprint','currency','total_cents','confirmed_at','confirm_fingerprint','reviewer','decision_note','expires_at','payment_mode')}

    def check_binding(self,quote,row):
        if row['approval_snapshot'] and json.loads(row['approval_snapshot'])!=self.binding(quote):
            raise Problem('approval_snapshot_mismatch',409)

    def dispatch_intent(self,db,key,action):
        db.execute('UPDATE orders SET capture_started_at=? WHERE quote_id=? AND capture_started_at IS NULL',(now(),key))
        db.execute("INSERT OR IGNORE INTO reconciliations(quote_id,state,updated) VALUES(?,'pending',?)",(key,now()))
        self.store.audit(db,key,action,{'outcome':'not_yet_known'})

    def revoke(self, key):
        """Stop future captures here; never claim a refund or remote cancellation."""
        with self.store.operation(key):
            with self.store.tx() as db:
                quote = db.execute('SELECT * FROM quotes WHERE id=?', (key,)).fetchone()
                if not quote:
                    raise Problem('quote_not_found', 404)
                if not quote['confirmed_at']:
                    raise Problem('human_confirmation_required', 409)
                if not quote['revoked_at']:
                    order = db.execute('SELECT * FROM orders WHERE quote_id=?', (key,)).fetchone()
                    if order and order['status'] in ('SANDBOX_PAID', 'SIMULATED_PAID'):
                        raise Problem('payment_already_completed', 409)
                    if order and order['capture_started_at'] and order['status'] != 'SIMULATED_DECLINED':
                        raise Problem('capture_may_have_started_reconcile_first', 409)
                    db.execute('UPDATE quotes SET revoked_at=? WHERE id=?', (now(), key))
                    self.store.audit(db, key, 'human_approval_revoked',
                                     {'fingerprint': quote['confirm_fingerprint'],
                                      'effect': 'blocks_future_scopepay_capture_only'})
            return self.store.quote(key)

    def _save(self, key, remote_id, summary, action):
        with self.store.operation(key):
            return self._commit_summary(key,remote_id,summary,action)

    def _commit_summary(self, key, remote_id, summary, action):
        quote = self.store.quote(key)
        with self.store.tx() as db:
            old = db.execute('SELECT status FROM orders WHERE quote_id=?', (key,)).fetchone()
            if old and old['status'] in ('SIMULATED_PAID', 'SANDBOX_PAID') and summary['status'] not in ('SIMULATED_PAID', 'SANDBOX_PAID'):
                # A later inconclusive response cannot erase a verified receipt.
                raise Problem('settled_order_changed_manual_review', 409)
            db.execute('UPDATE orders SET remote_id=?,status=?,body=? WHERE quote_id=?',
                       (remote_id, summary['status'], packed(summary), key))
            if not old or old['status']!=summary['status']:
                self.store.audit(db, key, action, {'status': summary['status'], 'mode': self.s.payment_mode})
            if summary['status'] in ('SIMULATED_PAID','SANDBOX_PAID','SIMULATED_DECLINED'):
                db.execute("UPDATE reconciliations SET state='resolved',lease_token=NULL,lease_until=0,last_code='',updated=? WHERE quote_id=?",(now(),key))
            if summary['status'] in ('SIMULATED_PAID', 'SANDBOX_PAID'):
                receipt = dict(id='SP-'+key.upper(), quote_id=key, order_id=remote_id, issued_at=now(),
                    title=quote.get('title', quote['items'][0]['title']), supplier=quote.get('supplier', ''),
                    mode=self.s.payment_mode, currency=quote['currency'], total_cents=quote['total_cents'],
                    fingerprint=quote['fingerprint'], items=quote['items'], payment_verified=summary['payment_verified'])
                db.execute('INSERT OR IGNORE INTO receipts(id,quote_id,order_id,body,created) VALUES(?,?,?,?,?)',
                    (receipt['id'], key, remote_id, packed(receipt), receipt['issued_at']))
        return self.view(key)

    def create(self, key, simulation_scenario='normal'):
        with self.store.operation(key):
            quote = self.require_active_approval(key)
            if self.s.payment_mode == 'sandbox' and not self.adapter.configured:
                raise Problem('sandbox_credentials_missing', 503)
            if self.s.payment_mode == 'sandbox' and not self.s.merchant_id:
                raise Problem('sandbox_merchant_id_missing',503)
            with self.store.tx() as db:
                db.execute('''INSERT OR IGNORE INTO orders
                    (quote_id,mode,request_id,capture_request_id,started,status,simulation_scenario,approval_snapshot) VALUES(?,?,?,?,?,?,?,?)''',
                    (key, self.s.payment_mode, new_id(), new_id(), time.time(), 'CREATING', simulation_scenario,packed(self.binding(quote))))
            row = self._row(key)
            self.check_binding(quote,row)
            if row['mode']=='simulation' and row['simulation_scenario']!=simulation_scenario:
                raise Problem('idempotency_parameters_changed',409)
            if row['remote_id']:
                return self.view(key)
            if time.time() - row['started'] > RETRY_WINDOW_SECONDS:
                raise Problem('uncertain_order_retry_expired_reconcile_manually', 409)
            if self.s.payment_mode == 'simulation':
                summary = dict(status='SIMULATED_CREATED', payment_verified=False,
                               evidence='Local deterministic simulation; no PayPal request',
                               currency=quote['currency'], total_cents=quote['total_cents'], approval_url=None)
                return self._save(key, 'SIM-' + key, summary, 'simulation_order_created')
            if row['create_lease_until']>time.time():
                raise Problem('operation_in_progress_retry_refresh',409)
            if row['create_attempts']>=3:
                raise Problem('order_creation_manual_review_required',409)
            with self.store.tx() as db:
                db.execute('UPDATE orders SET create_lease_until=?,create_attempts=create_attempts+1 WHERE quote_id=?',(time.time()+60,key))
        creation_failed=False
        try:
            raw = self.adapter.create(quote, row['request_id'])
            remote_id = raw.get('id', '')
            self.adapter.order_path(remote_id)
            # Save identity before the extra GET so a failed GET cannot trigger a new create.
            with self.store.operation(key),self.store.tx() as db:
                db.execute('UPDATE orders SET remote_id=?,status=? WHERE quote_id=?',
                           (remote_id, 'AWAITING_VERIFICATION', key))
        except BaseException:
            creation_failed=True
            raise
        finally:
            try:
                with self.store.operation(key),self.store.tx() as db:
                    db.execute('UPDATE orders SET create_lease_until=0 WHERE quote_id=?',(key,))
            except Exception:
                if not creation_failed:raise Problem('database_commit_unknown_refresh',503) from None
        return self.refresh(key)

    def refresh(self, key):
        with self.store.operation(key):
            row = self._row(key)
            if row['mode']=='simulation' and (not row['capture_started_at'] or row['status'] in ('SIMULATED_PAID','SIMULATED_DECLINED')):
                return self.view(key)
            if row['mode']=='sandbox' and not row['remote_id']:
                raise Problem('order_creation_uncertain_retry_same_quote', 409)
            if row['reconcile_lease_until']>time.time():
                raise Problem('operation_in_progress_retry_refresh',409)
            quote = self.store.quote(key)
            lease=new_id()
            with self.store.tx() as db:
                job=db.execute('SELECT * FROM reconciliations WHERE quote_id=?',(key,)).fetchone()
                if job and job['state']!='resolved':
                    if job['attempts']>=5:
                        raise Problem('reconciliation_manual_review_required',409)
                    if job['next_attempt']>time.time():
                        raise Problem('reconciliation_backoff_retry',429)
                    db.execute("UPDATE reconciliations SET state='checking',attempts=attempts+1,lease_token=?,lease_until=?,updated=? WHERE quote_id=?",(lease,time.time()+60,now(),key))
                db.execute('UPDATE orders SET reconcile_token=?,reconcile_lease_until=? WHERE quote_id=?',(lease,time.time()+60,key))
        failure=''
        try:
            if row['mode']=='simulation':
                with self.store.tx(read=True) as db:
                    captured=db.execute('SELECT body FROM simulated_captures WHERE quote_id=?',(key,)).fetchone()
                summary=json.loads(captured['body']) if captured else json.loads(row['body'])
            else:
                summary=verified_summary(self.adapter.get(row['remote_id']),quote,row['remote_id'],self.s.merchant_id)
            with self.store.operation(key):
                if self._row(key)['reconcile_token']!=lease:
                    raise Problem('stale_reconciliation_discarded',409)
                result=self._save(key,row['remote_id'],summary,'simulation_reconciled' if row['mode']=='simulation' else 'sandbox_order_verified')
            return result
        except Problem as exc:
            failure=exc.code
            raise
        finally:
            # Failed cleanup must not erase a provider error. The persisted lease
            # expires after process death / connection loss; no capture is replayed.
            try:
                with self.store.operation(key),self.store.tx() as db:
                    db.execute('UPDATE orders SET reconcile_lease_until=0 WHERE quote_id=? AND reconcile_token=?',(key,lease))
                    pending=db.execute('SELECT * FROM reconciliations WHERE quote_id=? AND lease_token=?',(key,lease)).fetchone()
                    if pending and pending['state']!='resolved':
                        db.execute('UPDATE reconciliations SET state=?,lease_until=0,next_attempt=?,last_code=?,updated=? WHERE quote_id=?',
                            ('manual' if pending['attempts']>=5 else 'pending',time.time()+min(60,2**pending['attempts']),failure or 'outcome_still_unknown',now(),key))
            except Exception:
                if not failure:raise Problem('database_commit_unknown_refresh',503) from None

    def simulate_approval(self, key):
        with self.store.operation(key):
            self.require_active_approval(key)
            row = self._row(key)
            if row['mode'] != 'simulation':
                raise Problem('simulation_disabled_in_sandbox', 403)
            if row['status'] != 'SIMULATED_CREATED':
                return self.view(key)
            summary = {**json.loads(row['body']), 'status': 'SIMULATED_APPROVED'}
            return self._save(key, row['remote_id'], summary, 'simulation_buyer_approved')

    def capture(self, key):
        with self.store.operation(key):
            quote = self.store.quote(key)
            if quote['revoked_at']:
                raise Problem('quote_approval_revoked', 409)
            if quote.get('declined_at'):
                raise Problem('quote_declined_use_revision', 409)
            row = self._row(key)
            if row['status'] in ('SIMULATED_PAID', 'SANDBOX_PAID'):
                return self.view(key)
            self.require_active_approval(key)
            self.check_binding(quote,row)
            if row['mode'] == 'simulation':
                if row['capture_started_at']:
                    raise Problem('capture_result_unknown_verify_first', 409)
                if row['status'] != 'SIMULATED_APPROVED':
                    raise Problem('buyer_approval_required', 409)
                with self.store.tx() as db:
                    self.dispatch_intent(db,key,'simulation_capture_dispatch_intent')
                if row['simulation_scenario'] == 'declined':
                    self._save(key, row['remote_id'], {**json.loads(row['body']), 'status': 'SIMULATED_DECLINED'}, 'simulation_payment_declined')
                    raise Problem('payment_declined_use_revision', 409)
                summary = {**json.loads(row['body']), 'status': 'SIMULATED_PAID', 'payment_verified': False}
                with self.store.tx() as db:
                    db.execute('INSERT OR IGNORE INTO simulated_captures(quote_id,body) VALUES(?,?)', (key, packed(summary)))
                if row['simulation_scenario'] == 'response_lost':
                    raise Problem('simulation_response_lost_verify_status', 504)
                return self._save(key, row['remote_id'], summary, 'simulation_capture')
        current = self.refresh(key)
        with self.store.operation(key):
            quote=self.require_active_approval(key)
            row=self._row(key)
            self.check_binding(quote,row)
            if current.get('payment_verified'):
                return current
            if row['capture_started_at']:
                raise Problem('capture_result_unknown_verify_first', 409)
            if current.get('remote_status') != 'APPROVED':
                raise Problem('buyer_approval_required', 409)
            if time.time() - row['started'] > RETRY_WINDOW_SECONDS:
                raise Problem('order_retry_window_expired_reconcile_manually', 409)
            # Commit before sending anything: a timeout/crash cannot later be
            # misreported as successful revocation. A GET of APPROVED is not
            # proof that an in-flight capture will never complete.
            with self.store.tx() as db:
                self.dispatch_intent(db,key,'sandbox_capture_dispatch_intent')
        self.adapter.capture(row['remote_id'], row['capture_request_id'])
        return self.refresh(key)

    def webhook(self, headers, event):
        if self.s.payment_mode != 'sandbox':
            raise Problem('webhooks_unavailable_in_simulation', 409)
        if not isinstance(event, dict) or not isinstance(event.get('id'), str) or len(event['id']) > 150:
            raise Problem('invalid_webhook_event', 400)
        self.adapter.verify(headers, event)
        # Verification/refetch waits must not hold a global webhook lock. The
        # unique event ID makes recording idempotent after a successful refetch.
        with self.store.tx(read=True) as db:
            if db.execute('SELECT 1 FROM events WHERE id=?', (event['id'],)).fetchone():
                return {'accepted': True, 'duplicate': True}
        kind = event.get('event_type', '')
        resource = event.get('resource') or {}
        if not isinstance(resource, dict):
            raise Problem('invalid_webhook_event', 400)
        supplementary = resource.get('supplementary_data') or {}
        related = supplementary.get('related_ids') if isinstance(supplementary, dict) else None
        remote_id = (resource.get('id') if kind == 'CHECKOUT.ORDER.APPROVED' else
                     related.get('order_id') if isinstance(related, dict) else None)
        supported = kind in ('CHECKOUT.ORDER.APPROVED', 'PAYMENT.CAPTURE.COMPLETED', 'PAYMENT.CAPTURE.DENIED')
        with self.store.tx(read=True) as db:
            row = db.execute('SELECT quote_id FROM orders WHERE remote_id=? AND mode=?',
                             (remote_id, 'sandbox')).fetchone() if isinstance(remote_id, str) else None
        if row and supported:
            self.refresh(row['quote_id'])  # Never trust status or amount in callback payload.
        with self.store.tx() as db:
            inserted=db.execute('INSERT OR IGNORE INTO events(id,received) VALUES(?,?)', (event['id'], now())).rowcount
            if not inserted:return {'accepted':True,'duplicate':True}
            self.store.audit(db, row['quote_id'] if row else 'webhook', 'verified_webhook',
                             {'type': kind, 'reconciled': bool(row and supported)})
        return {'accepted': True, 'duplicate': False, 'reconciled': bool(row and supported)}
