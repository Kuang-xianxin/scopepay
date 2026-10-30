"""Purchase drafts, immutable review snapshots and durable register."""
import json
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Literal

from pydantic import Field, StrictInt

from .core import (Cents, Confirmation, Currency, PositiveInt, Problem, StrictModel,
                   digest, money, new_id, now, packed)


class DraftLine(StrictModel):
    title: str = Field(default='', max_length=250)
    quantity: PositiveInt = 1
    unit_cents: StrictInt = Field(default=0, ge=0, le=10_000_000)
    included: bool = True
    evidence_quote: str = Field(default='', max_length=1500)


class DraftInput(StrictModel):
    expected_version: StrictInt = Field(ge=0)
    title: str = Field(default='', max_length=160)
    supplier: str = Field(default='', max_length=160)
    source: str = Field(default='', max_length=12000)
    currency: Currency = 'USD'
    budget_cents: StrictInt = Field(default=0, ge=0, le=10_000_000)
    expires_at: str = Field(default='', max_length=40)
    notes: str = Field(default='', max_length=2000)
    items: list[DraftLine] = Field(default_factory=list, max_length=20)
    analysis_id: str | None = Field(default=None, max_length=40)


class Review(Confirmation):
    reviewer: str = Field(default='Local operator', min_length=1, max_length=100)
    note: str = Field(default='', max_length=1000)


class Decline(StrictModel):
    fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    reviewer: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=1000)


class OrderInput(Confirmation):
    simulation_scenario: Literal['normal', 'response_lost', 'declined'] = 'normal'


def expired(q):
    value = q.get('expires_at')
    return bool(value and datetime.fromisoformat(value) <= datetime.now(timezone.utc))


def active(q, require_confirmation=True):
    if q.get('revoked_at'):
        raise Problem('quote_approval_revoked', 409)
    if q.get('declined_at'):
        raise Problem('quote_declined_use_revision', 409)
    if expired(q):
        raise Problem('approval_expired_use_revision', 409)
    if require_confirmation and not q.get('confirmed_at'):
        raise Problem('human_confirmation_required', 409)
    if require_confirmation and q.get('confirm_fingerprint') != q.get('fingerprint'):
        raise Problem('approval_snapshot_mismatch',409)


def state(q, o=None):
    o = o or {}
    if o.get('status') in ('SANDBOX_PAID', 'SIMULATED_PAID'):
        return 'paid'
    if o.get('status') == 'SIMULATED_DECLINED':
        return 'payment_declined'
    if o.get('capture_started_at'):
        return 'unknown'
    if q.get('revoked_at'):
        return 'revoked'
    if q.get('declined_at'):
        return 'declined'
    if expired(q):
        return 'expired'
    if not q.get('confirmed_at'):
        return 'review'
    if o.get('status') in ('SIMULATED_APPROVED', 'APPROVED'):
        return 'capture_ready'
    if o:
        return 'awaiting_buyer' if o.get('order_id') else 'creating'
    return 'approved'


class Workspace:
    def __init__(self, store, settings, payments):
        self.store, self.settings, self.payments = store, settings, payments

    def draft(self, key):
        with self.store.tx(read=True) as db:
            row = db.execute('SELECT * FROM drafts WHERE id=?', (key,)).fetchone()
        if not row:
            raise Problem('draft_not_found', 404)
        return {**json.loads(row['body']), 'id': key, 'version': row['version'],
                'created_at': row['created'], 'updated_at': row['updated'], 'quote_id': row['quote_id']}

    def save(self, key, body):
        from uuid import UUID
        try:
            UUID(key)
        except ValueError:
            raise Problem('invalid_draft_id', 422)
        data = body.model_dump(exclude={'expected_version'})
        if data['analysis_id']:
            analysis = self.store.analysis(data['analysis_id'])
            if analysis['source'] != body.source:
                raise Problem('source_changed_extract_again', 409)
        for line in data['items']:
            if line['evidence_quote'] and line['evidence_quote'] not in body.source:
                raise Problem('evidence_not_in_source', 422)
        with self.store.operation('draft:' + key), self.store.tx() as db:
            row = db.execute('SELECT * FROM drafts WHERE id=?', (key,)).fetchone()
            if row and row['quote_id']:
                raise Problem('submitted_draft_is_immutable', 409)
            if (row and row['version'] != body.expected_version) or (not row and body.expected_version != 0):
                raise Problem('draft_changed_reload_before_save', 409)
            if row:
                data['parent_quote_id'] = json.loads(row['body']).get('parent_quote_id')
                db.execute('UPDATE drafts SET body=?,version=version+1,updated=? WHERE id=?', (packed(data), now(), key))
            else:
                db.execute('INSERT INTO drafts(id,body,version,created,updated) VALUES(?,?,?,?,?)', (key, packed(data), 1, now(), now()))
                self.store.audit(db, key, 'draft_created')
            self.store.index(db, key, 'draft', data, now())
        return self.draft(key)

    def submit(self, key):
        with self.store.operation('draft:' + key):
            draft = self.draft(key)
            if draft['quote_id']:
                return self.store.quote(draft['quote_id'])
            if not draft['title'].strip() or not draft['supplier'].strip():
                raise Problem('purchase_title_and_supplier_required', 422)
            selected = [x for x in draft['items'] if x['included']]
            if not selected:
                raise Problem('select_at_least_one_item', 422)
            if any(not x['title'].strip() or x['unit_cents'] < 1 for x in selected):
                raise Problem('included_items_need_title_and_price', 422)
            total = sum(x['quantity'] * x['unit_cents'] for x in selected)
            if total > draft['budget_cents']:
                raise Problem('quote_exceeds_budget', 422)
            try:
                deadline = datetime.fromisoformat(draft['expires_at'].replace('Z', '+00:00'))
                if deadline.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise Problem('approval_deadline_required', 422)
            current = datetime.now(timezone.utc)
            if not current < deadline <= current + timedelta(days=90):
                raise Problem('deadline_must_be_future_within_90_days', 422)
            analysis = self.store.analysis(draft['analysis_id']) if draft['analysis_id'] else dict(
                id=new_id(), created_at=now(), source=draft['source'], source_sha256=hashlib.sha256(draft['source'].encode('utf-8')).hexdigest(),
                provenance={'kind': 'manual', 'model': None}, requires_human_review=True,
                deliverables=[{'id': f'd{i+1}', 'title': line['title'], 'evidence': self.evidence(draft['source'], line['evidence_quote'])} for i, line in enumerate(draft['items'])], risks=[], questions=[])
            q = dict(id=new_id(), draft_id=key, analysis_id=analysis['id'], title=draft['title'].strip(),
                supplier=draft['supplier'].strip(), created_at=now(), currency=draft['currency'],
                budget_cents=draft['budget_cents'], total_cents=total, total_display=money(total),
                source_sha256=analysis['source_sha256'], notes=draft['notes'], expires_at=deadline.astimezone(timezone.utc).isoformat(),
                parent_quote_id=draft.get('parent_quote_id'), payment_mode=self.settings.payment_mode,
                price_origin='human_input', taxes_and_fees='explicit_lines_only',
                extraction_provenance=analysis['provenance'],
                items=[dict(deliverable_id=f'd{i+1}', title=x['title'], quantity=x['quantity'], unit_cents=x['unit_cents'],
                            line_cents=x['quantity']*x['unit_cents'], evidence=self.evidence(draft['source'], x['evidence_quote']))
                       for i, x in enumerate(draft['items']) if x['included']],
                excluded_items=[x['title'] for x in draft['items'] if not x['included']],
                excluded_deliverable_ids=[f'd{i+1}' for i, x in enumerate(draft['items']) if not x['included']])
            q['fingerprint'] = digest(q)
            with self.store.tx() as db:
                db.execute('INSERT OR IGNORE INTO analyses(id,body) VALUES(?,?)', (analysis['id'], packed(analysis)))
                db.execute('INSERT INTO quotes(id,body) VALUES(?,?)', (q['id'], packed(q)))
                db.execute('UPDATE drafts SET quote_id=?,updated=? WHERE id=?', (q['id'], now(), key))
                # Keep the draft in history, hide its index row through the read join.
                self.store.index(db, q['id'], 'quote', q, q['created_at'])
                self.store.audit(db, q['id'], 'quote_created', {'total_cents': total, 'currency': q['currency'], 'budget_cents': q['budget_cents']})
            return self.store.quote(q['id'])

    @staticmethod
    def evidence(source, quote):
        start = source.find(quote) if quote else -1
        return {'quote': quote, 'start': start, 'end': start + len(quote) if start >= 0 else -1}

    def revise(self, key):
        with self.store.operation(key):
            q = self.store.quote(key)
            with self.store.tx(read=True) as db:
                order = db.execute('SELECT * FROM orders WHERE quote_id=?', (key,)).fetchone()
                previous = db.execute('SELECT * FROM drafts WHERE id=?', (q.get('draft_id', ''),)).fetchone()
                existing = db.execute('SELECT d.* FROM drafts d JOIN purchase_index p ON p.id=d.id WHERE d.quote_id IS NULL AND p.parent_quote_id=?', (key,)).fetchall()
            if order and (order['status'] in ('SIMULATED_PAID', 'SANDBOX_PAID') or
                          (order['capture_started_at'] and order['status'] != 'SIMULATED_DECLINED')):
                raise Problem('capture_may_have_started_reconcile_first', 409)
            if q['confirmed_at'] and not (q['revoked_at'] or expired(q) or (order and order['status'] == 'SIMULATED_DECLINED')):
                raise Problem('revoke_before_revision', 409)
            for row in existing:
                if json.loads(row['body']).get('parent_quote_id') == key:
                    return self.draft(row['id'])
            if previous:
                data = json.loads(previous['body'])
            else:
                analysis = self.store.analysis(q['analysis_id'])
                data = dict(title=q.get('title', 'Revised purchase'), supplier=q.get('supplier', ''), source=analysis['source'],
                    currency=q['currency'], budget_cents=q['total_cents'], notes='', analysis_id=analysis['id'],
                    items=[dict(title=x['title'], quantity=x['quantity'], unit_cents=x['unit_cents'], included=True, evidence_quote=x['evidence']['quote']) for x in q['items']])
            data.update(parent_quote_id=key, expires_at=(datetime.now(timezone.utc)+timedelta(days=7)).isoformat())
            ident = new_id()
            with self.store.tx() as db:
                if not q['confirmed_at'] and not q['declined_at']:
                    db.execute('UPDATE quotes SET declined_at=?,decision_note=? WHERE id=?', (now(), 'Superseded by revision', key))
                db.execute('INSERT INTO drafts(id,body,version,created,updated) VALUES(?,?,?,?,?)', (ident, packed(data), 1, now(), now()))
                self.store.audit(db, key, 'revision_started', {'draft_id': ident})
                self.store.index(db, ident, 'draft', data, now())
            return self.draft(ident)

    def snapshot(self, key, export=False):
        with self.store.operation(key):
            q = self.store.quote(key)
            try:
                order = self.payments.view(key)
            except Problem as exc:
                if exc.code != 'order_not_created':
                    raise
                order = None
            with self.store.tx(read=True) as db:
                receipt = db.execute('SELECT body FROM receipts WHERE quote_id=?', (key,)).fetchone()
                cap=5000 if export else 200
                audit = db.execute('SELECT * FROM audit WHERE entity IN (?,?) ORDER BY seq DESC LIMIT ?', (key, q['analysis_id'],cap+1)).fetchall()
                reconcile=db.execute('SELECT state,attempts,next_attempt,last_code,updated FROM reconciliations WHERE quote_id=?',(key,)).fetchone()
            receipt=json.loads(receipt['body']) if receipt else None
            if export and len(audit)>cap:raise Problem('export_history_limit_use_paged_audit',413)
            if receipt and any(receipt.get(k)!=v for k,v in {'quote_id':key,'order_id':order['order_id'] if order else None,'fingerprint':q['fingerprint'],'total_cents':q['total_cents'],'currency':q['currency']}.items()):
                raise Problem('receipt_integrity_mismatch',409)
            return dict(project='ScopePay', schema_version=2, quote=q, analysis=self.store.analysis(q['analysis_id']),
                order=order, status=state(q, order), receipt=receipt,reconciliation=dict(reconcile) if reconcile else None,
                audit_truncated=len(audit)>cap,
                audit=[dict(seq=r['seq'], action=r['action'], created=r['created'], data=json.loads(r['data'])) for r in reversed(audit[:cap])])

    def register(self, search='', status='all', offset=0, limit=50):
        cte = '''WITH register AS (SELECT p.*,CASE
            WHEN p.kind='draft' THEN 'draft'
            WHEN o.status IN ('SIMULATED_PAID','SANDBOX_PAID') THEN 'paid'
            WHEN o.status='SIMULATED_DECLINED' THEN 'payment_declined'
            WHEN o.capture_started_at IS NOT NULL THEN 'unknown'
            WHEN q.revoked_at IS NOT NULL THEN 'revoked'
            WHEN q.declined_at IS NOT NULL THEN 'declined'
            WHEN p.expires_at IS NOT NULL AND p.expires_at<=? THEN 'expired'
            WHEN q.confirmed_at IS NULL THEN 'review'
            WHEN o.status IN ('SIMULATED_APPROVED','APPROVED') THEN 'capture_ready'
            WHEN o.remote_id IS NOT NULL THEN 'awaiting_buyer'
            WHEN o.quote_id IS NOT NULL THEN 'creating' ELSE 'approved' END AS status
            FROM purchase_index p LEFT JOIN quotes q ON p.id=q.id
            LEFT JOIN orders o ON p.id=o.quote_id LEFT JOIN drafts d ON p.id=d.id
            WHERE p.kind='quote' OR d.quote_id IS NULL) '''
        where, params = [], [now()]
        if search.strip():
            term='%'+search.strip().lower().replace('!','!!').replace('%','!%').replace('_','!_')+'%'
            where.append("(LOWER(title) LIKE ? ESCAPE '!' OR LOWER(supplier) LIKE ? ESCAPE '!' OR id LIKE ? ESCAPE '!')")
            params += [term,term,term]
        if status == 'attention':
            where.append("status IN ('review','unknown','creating','payment_declined')")
        elif status != 'all':
            where.append('status=?');params.append(status)
        clause=' WHERE '+' AND '.join(where) if where else ''
        with self.store.tx(read=True) as db:
            counts={r['status']:r['n'] for r in db.execute(cte+'SELECT status,COUNT(*) AS n FROM register GROUP BY status',(params[0],)).fetchall()}
            if not search.strip():
                total=(sum(counts.values()) if status=='all' else sum(counts.get(k,0) for k in ('review','unknown','creating','payment_declined')) if status=='attention' else counts.get(status,0))
            else:
                total=db.execute(cte+'SELECT COUNT(*) AS n FROM register'+clause,tuple(params)).fetchone()['n']
            if status=='all' and not search.strip():
                # Page the compact projection before joining immutable quote/order
                # facts. Counts still inspect metadata; no source JSON is loaded.
                page='WITH page AS (SELECT p.* FROM purchase_index p WHERE p.kind=\'quote\' OR EXISTS(SELECT 1 FROM drafts d WHERE d.id=p.id AND d.quote_id IS NULL) ORDER BY p.updated_at DESC,p.id LIMIT ? OFFSET ?), '
                page_cte=page+cte.removeprefix('WITH ').replace('FROM purchase_index p','FROM page p')
                rows=db.execute(page_cte+'SELECT id,kind,title,supplier,currency,total_cents,updated_at,status FROM register ORDER BY updated_at DESC,id',(limit,offset,params[0])).fetchall()
            else:
                rows=db.execute(cte+'SELECT id,kind,title,supplier,currency,total_cents,updated_at,status FROM register'+clause+' ORDER BY updated_at DESC,id LIMIT ? OFFSET ?',tuple(params+[limit,offset])).fetchall()
        return dict(items=[dict(r) for r in rows],total=total,counts=counts,offset=offset,limit=limit)
