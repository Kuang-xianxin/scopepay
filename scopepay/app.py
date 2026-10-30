import json
import secrets
import threading
import time
from datetime import datetime,timezone,timedelta
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .core import (ROOT, AnalysisInput, Confirmation, Empty, Problem, QuoteInput,
                   Settings, Store, digest, money, new_id, now, packed)
from .extraction import Extractor
from .payments import PayPal, Payments
from .workspace import Workspace, DraftInput, Review, Decline, OrderInput, active
from .admission import AdmissionMiddleware
from .execution import bounded_routes


def create_app(settings=None, model_transport=None, payment_transport=None):
    s = settings or Settings.from_env()
    store = Store(s.database_url or s.db_path)
    extractor = Extractor(s, model_transport)
    adapter = PayPal(s, payment_transport)
    payments = Payments(store, s, adapter)
    # Persist a local anti-CSRF token so multiple workers and restarts agree.
    # It is not a remote-user authentication credential.
    import hashlib
    token_file = Path(s.db_path).parent / 'local-session.key'
    token_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with token_file.open('x', encoding='utf-8') as file:
            file.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    token = token_file.read_text(encoding='utf-8').strip()
    workspace = Workspace(store, s, payments)
    @asynccontextmanager
    async def lifespan(app):
        yield
        store.close()
    app = FastAPI(title='ScopePay', version='1.2.1', lifespan=lifespan, description='Private purchase scope and payment review.')
    model_slots = threading.BoundedSemaphore(1)
    app.state.model_slots = model_slots
    app.state.metrics = {'requests': 0, 'rejected': 0, 'errors': 0, 'active': 0, 'max_active': 0, 'total_ms': 0}
    app.router.route_class=bounded_routes(app.state.metrics)
    app.state.store, app.state.payments, app.state.settings = store, payments, s
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.exception_handler(Problem)
    async def problem_handler(_, exc):
        return JSONResponse({'error': exc.code}, status_code=exc.status,
            headers={'Retry-After':'2'} if exc.status in (429,503) else None)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_, exc):
        return JSONResponse({'error': 'invalid_input', 'fields': [
            {'path': '.'.join(str(x) for x in e['loc']), 'type': e['type']} for e in exc.errors()]}, status_code=422)

    @app.middleware('http')
    async def local_boundary(request: Request, call_next):
        if request.client and request.client.host not in ('127.0.0.1','::1','localhost','testclient'):
            return JSONResponse({'error':'private_workspace_loopback_only'},status_code=403)
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            if request.url.path != '/api/webhooks/paypal':
                origin = request.headers.get('origin')
                if origin and origin != s.app_url:
                    return JSONResponse({'error': 'cross_origin_forbidden'}, status_code=403)
                if not secrets.compare_digest(request.headers.get('x-scopepay-token', ''), token):
                    return JSONResponse({'error': 'local_session_required'}, status_code=403)
            if request.headers.get('content-type', '').split(';')[0] != 'application/json':
                return JSONResponse({'error': 'json_required'}, status_code=415)
            # Bound the actual streamed body, not only a client-supplied Content-Length.
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 65536:
                    return JSONResponse({'error': 'body_too_large'}, status_code=413)
                chunks.append(chunk)
            request._body = b''.join(chunks)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        return response

    app.add_middleware(AdmissionMiddleware, metrics=app.state.metrics)

    @app.get('/api/metrics')
    def metrics():
        return {**app.state.metrics, 'database_pool':store.pool.get_stats() if store.pool else {}, 'scope':'this_worker_lifetime'}

    @app.get('/api/health')
    def health():
        return {'ok': True, 'project': 'ScopePay', 'payment_mode': s.payment_mode,
                'sandbox_configured': adapter.configured, 'webhook_configured': bool(s.webhook_id),
                'sandbox_merchant_configured': bool(s.merchant_id),
                'model_configured': bool(s.model), 'model': s.model or None,
                'model_live_verified': 'not_probed_by_health', 'production_supported': False}

    @app.get('/api/ready')
    def ready():
        try:
            with store.tx(read=True) as db:
                db.execute('SELECT version FROM schema_migrations').fetchone()
        except Exception:
            return JSONResponse({'ready': False, 'database': 'unavailable'}, status_code=503)
        return {'ready': True, 'database': 'postgresql' if store.postgres else 'sqlite',
                'payment_mode': s.payment_mode, 'sandbox_ready': False,
                'sandbox_configuration_complete': bool(adapter.configured and s.merchant_id),
                'sandbox_verification': 'not_probed_use_preflight',
                'inference': 'configured_not_probed' if s.model else 'not_configured'}

    @app.get('/api/session')
    def session():
        return {'token': token}

    @app.post('/api/analyses')
    def analyse(body: AnalysisInput):
        if body.mode == 'model' and not model_slots.acquire(blocking=False):
            raise Problem('model_busy_retry', 429)
        try:
            result = extractor.extract(body.source, body.mode)
        finally:
            if body.mode == 'model': model_slots.release()
        with store.tx() as db:
            db.execute('INSERT INTO analyses(id,body) VALUES(?,?)', (result['id'], packed(result)))
            store.audit(db, result['id'], 'scope_extracted', result['provenance'])
        return result

    @app.get('/api/analyses/{key}')
    def analysis(key: str):
        return store.analysis(key)

    @app.post('/api/quotes')
    def price(body: QuoteInput):
        analysis = store.analysis(body.analysis_id)
        by_id = {d['id']: d for d in analysis['deliverables']}
        ids = [item.deliverable_id for item in body.items]
        if len(ids) != len(set(ids)):
            raise Problem('duplicate_deliverable', 422)
        if any(key not in by_id for key in ids):
            raise Problem('unknown_deliverable', 422)
        items = [{**item.model_dump(), 'title': by_id[item.deliverable_id]['title'],
                  'evidence': by_id[item.deliverable_id]['evidence'],
                  'line_cents': item.quantity * item.unit_cents} for item in body.items]
        total = sum(item['line_cents'] for item in items)
        if total > 10_000_000:
            raise Problem('quote_total_exceeds_demo_limit', 422)
        quote = dict(id=new_id(), analysis_id=analysis['id'], source_sha256=analysis['source_sha256'],
                     created_at=now(), currency=body.currency, items=items, total_cents=total,
                     budget_cents=total, expires_at=(datetime.now(timezone.utc)+timedelta(days=7)).isoformat(),
                     total_display=money(total), payment_mode=s.payment_mode,
                     excluded_deliverable_ids=[key for key in by_id if key not in ids],
                     price_origin='human_input', taxes_and_fees='not_calculated',
                     extraction_provenance=analysis['provenance'])
        quote['fingerprint'] = digest(quote)
        with store.tx() as db:
            db.execute('INSERT INTO quotes(id,body) VALUES(?,?)', (quote['id'], packed(quote)))
            store.audit(db, quote['id'], 'quote_created', {'total_cents': total, 'currency': body.currency})
            store.index(db, quote['id'], 'quote', quote, quote['created_at'])
        return {**quote, 'confirmed_at': None, 'revoked_at': None}

    @app.get('/api/quotes/{key}')
    def get_quote(key: str):
        return store.quote(key)

    def validate_confirmation(key, body):
        q = store.quote(key)
        source=store.analysis(q['analysis_id'])
        if q.get('source_sha256') != source.get('source_sha256'):
            raise Problem('source_integrity_mismatch',409)
        if (q['fingerprint'] != body.fingerprint or q['currency'] != body.expected_currency
                or q['total_cents'] != body.expected_total_cents):
            raise Problem('confirmation_amount_currency_or_fingerprint_mismatch', 409)
        if q['payment_mode'] != s.payment_mode:
            raise Problem('quote_mode_changed_use_new_quote', 409)
        return q

    @app.post('/api/quotes/{key}/confirm')
    def confirm(key: str, body: Review):
        q = validate_confirmation(key, body)
        with store.operation(key):
            active(store.quote(key), require_confirmation=False)
            with store.tx() as db:
                prior=db.execute('SELECT * FROM quotes WHERE id=?', (key,)).fetchone()
                if prior['revoked_at']:
                    raise Problem('quote_approval_revoked', 409)
                if prior['confirmed_at'] and (prior['confirm_fingerprint']!=q['fingerprint'] or prior['reviewer']!=body.reviewer or prior['decision_note']!=body.note):
                    raise Problem('approval_snapshot_mismatch',409)
                changed = db.execute('''UPDATE quotes SET confirmed_at=?,confirm_fingerprint=?,reviewer=?,decision_note=?
                    WHERE id=? AND confirmed_at IS NULL''', (now(), q['fingerprint'], body.reviewer, body.note, key)).rowcount
                if changed:
                    store.audit(db, key, 'human_confirmed', {'fingerprint': q['fingerprint'],
                        'currency': q['currency'], 'total_cents': q['total_cents'], 'reviewer': body.reviewer})
        return store.quote(key)

    @app.post('/api/quotes/{key}/revoke')
    def revoke(key: str, body: Confirmation):
        validate_confirmation(key, body)
        return payments.revoke(key)

    @app.post('/api/quotes/{key}/order')
    def create_order(key: str, body: OrderInput):
        validate_confirmation(key, body)
        return payments.create(key, body.simulation_scenario)

    @app.post('/api/quotes/{key}/decline')
    def decline(key: str, body: Decline):
        with store.operation(key):
            q = store.quote(key)
            if q['fingerprint'] != body.fingerprint:
                raise Problem('confirmation_amount_currency_or_fingerprint_mismatch', 409)
            if q['confirmed_at']:
                raise Problem('revoke_before_revision', 409)
            if not q['declined_at']:
                with store.tx() as db:
                    db.execute('UPDATE quotes SET declined_at=?,reviewer=?,decision_note=? WHERE id=?', (now(), body.reviewer, body.note, key))
                    store.audit(db, key, 'quote_declined', {'reviewer': body.reviewer, 'note': body.note})
        return store.quote(key)

    @app.get('/api/purchases')
    def purchases(search: str = '', status: str = 'all', offset: int = 0, limit: int = 50):
        if not 0 <= offset <= 10000 or not 1 <= limit <= 100 or len(search) > 200:
            raise Problem('invalid_input', 422)
        return workspace.register(search, status, offset, limit)

    @app.put('/api/drafts/{key}')
    def save_draft(key: str, body: DraftInput):
        return workspace.save(key, body)

    @app.get('/api/drafts/{key}')
    def get_draft(key: str):
        return workspace.draft(key)

    @app.post('/api/drafts/{key}/submit')
    def submit_draft(key: str, body: Empty):
        return workspace.submit(key)

    @app.post('/api/quotes/{key}/revise')
    def revise(key: str, body: Empty):
        return workspace.revise(key)

    @app.get('/api/quotes/{key}/snapshot')
    def snapshot(key: str):
        return workspace.snapshot(key)

    @app.get('/api/quotes/{key}/export')
    def export(key: str):
        return JSONResponse(workspace.snapshot(key,export=True), headers={
            'Content-Disposition': f'attachment; filename="scopepay-{key}.json"'})

    @app.get('/api/quotes/{key}/order')
    def order(key: str):
        return payments.view(key)

    @app.post('/api/quotes/{key}/refresh')
    def refresh(key: str, body: Empty):
        return payments.refresh(key)

    @app.post('/api/quotes/{key}/simulate-approval')
    def simulate(key: str, body: Empty):
        return payments.simulate_approval(key)

    @app.post('/api/quotes/{key}/capture')
    def capture(key: str, body: Confirmation):
        validate_confirmation(key, body)
        return payments.capture(key)

    @app.post('/api/webhooks/paypal')
    def webhook(request: Request, body: dict):
        return payments.webhook(request.headers, body)

    @app.get('/api/quotes/{key}/audit')
    def audit(key: str, before: int = 0, limit: int = 200):
        if before<0 or not 1<=limit<=200:raise Problem('invalid_input',422)
        q = store.quote(key)
        with store.tx(read=True) as db:
            rows = db.execute('SELECT * FROM audit WHERE entity IN (?,?) AND (?=0 OR seq<?) ORDER BY seq DESC LIMIT ?',
                              (key, q['analysis_id'],before,before,limit)).fetchall()
        return [dict(seq=r['seq'], action=r['action'], created=r['created'], data=json.loads(r['data'])) for r in reversed(rows)]

    @app.get('/')
    def home():
        return FileResponse(ROOT / 'static/workspace.html')

    @app.get('/static/style.css')
    def css():
        # Windows registry MIME overrides can otherwise return text/plain,
        # which browsers correctly reject with X-Content-Type-Options: nosniff.
        return FileResponse(ROOT / 'static/workspace.css', media_type='text/css')

    @app.get('/static/app.js')
    def javascript():
        return FileResponse(ROOT / 'static/workspace.js', media_type='text/javascript')

    @app.get('/static/translations.js')
    def translations():
        return FileResponse(ROOT / 'static/translations.js', media_type='text/javascript')

    @app.get('/static/contracts.js')
    def contracts():
        return FileResponse(ROOT / 'static/contracts.js', media_type='text/javascript')

    return app
