"""SQLite/PostgreSQL transactions and cross-process operations; no destructive migration."""
import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse, parse_qs


class Connection:
    def __init__(self, raw, postgres):
        self.raw, self.postgres = raw, postgres

    def execute(self, sql, params=()):
        if self.postgres:
            ignore = 'INSERT OR IGNORE' in sql.upper()
            sql = sql.replace('INSERT OR IGNORE', 'INSERT').replace('?', '%s')
            if ignore:
                sql += ' ON CONFLICT DO NOTHING'
        return self.raw.execute(sql, params)


class Store:
    def __init__(self, path):
        self.path = path
        self.postgres = str(path).startswith(('postgresql://', 'postgres://'))
        self._local = threading.local()
        self.operation_slots = threading.BoundedSemaphore(2)
        self.pool = None
        self.options = (parse_qs(urlparse(path).query).get('options',[''])[0]+' ' if self.postgres else '') + '-c statement_timeout=5000 -c lock_timeout=2000 -c idle_in_transaction_session_timeout=10000'
        if not self.postgres:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.migrate()
        if self.postgres:
            from psycopg_pool import ConnectionPool
            from psycopg.rows import dict_row
            import logging
            # Driver reconnect exceptions may include connection options. Export
            # only our bounded counters; never log pool exception reprs.
            logging.getLogger('psycopg.pool').disabled = True
            self.pool = ConnectionPool(self.path, min_size=1, max_size=4, max_waiting=8,
                timeout=2, max_idle=60, reconnect_timeout=5, open=True,
                kwargs={'row_factory': dict_row, 'connect_timeout': 3,
                        'options': self.options})

    def close(self):
        if self.pool:
            self.pool.close()

    def connect(self):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            return psycopg.connect(self.path, row_factory=dict_row, connect_timeout=3,
                options=self.options)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=10000')
        db.execute('PRAGMA synchronous=FULL')
        return db

    @contextmanager
    def tx(self, read=False):
        from .core import Problem
        committing=False
        try:
            db = self.pool.getconn(timeout=2) if self.pool else self.connect()
        except Exception:
            raise Problem('database_busy_retry', 503) from None
        try:
            if not self.postgres:
                db.execute('BEGIN' if read else 'BEGIN IMMEDIATE')
            elif read:
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            yield Connection(db, self.postgres)
            committing=True
            db.commit()
        except Exception as exc:
            try:db.rollback()
            except Exception:
                try:db.close()
                except Exception:pass
            if committing:
                raise Problem('database_commit_unknown_refresh',503) from None
            if self.postgres and type(exc).__name__ in ('QueryCanceled', 'LockNotAvailable', 'DeadlockDetected', 'OperationalError', 'InterfaceError'):
                raise Problem('database_busy_retry', 503) from None
            if isinstance(exc, sqlite3.OperationalError):
                if getattr(exc,'sqlite_errorcode',0) in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
                    raise Problem('database_busy_retry',503) from None
                raise Problem('database_write_failed_keep_state',507) from None
            raise
        finally:
            self.release(db)

    def release(self, db):
        # Cleanup cannot replace a business exception or leak a failed connection.
        try:
            if self.pool:self.pool.putconn(db)
            else:db.close()
        except Exception:
            try:db.close()
            except Exception:pass

    def migrate(self):
        with self.tx() as db:
            if self.postgres:
                db.execute('SELECT pg_advisory_xact_lock(82150001)')
            serial = 'BIGSERIAL PRIMARY KEY' if self.postgres else 'INTEGER PRIMARY KEY AUTOINCREMENT'
            statements = [
                'CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS analyses(id TEXT PRIMARY KEY, body TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS quotes(id TEXT PRIMARY KEY, body TEXT NOT NULL, confirmed_at TEXT, confirm_fingerprint TEXT, revoked_at TEXT)',
                "CREATE TABLE IF NOT EXISTS orders(quote_id TEXT PRIMARY KEY,mode TEXT NOT NULL,request_id TEXT NOT NULL,capture_request_id TEXT NOT NULL,started DOUBLE PRECISION NOT NULL,remote_id TEXT UNIQUE,status TEXT NOT NULL,body TEXT NOT NULL DEFAULT '{}',capture_started_at TEXT)",
                'CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,received TEXT NOT NULL)',
                f'CREATE TABLE IF NOT EXISTS audit(seq {serial},entity TEXT NOT NULL,action TEXT NOT NULL,created TEXT NOT NULL,data TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY,body TEXT NOT NULL,version INTEGER NOT NULL CHECK(version>0),created TEXT NOT NULL,updated TEXT NOT NULL,quote_id TEXT UNIQUE REFERENCES quotes(id))',
                'CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,quote_id TEXT NOT NULL UNIQUE REFERENCES quotes(id),order_id TEXT NOT NULL UNIQUE,body TEXT NOT NULL,created TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS simulated_captures(quote_id TEXT PRIMARY KEY REFERENCES quotes(id),body TEXT NOT NULL)',
                'CREATE INDEX IF NOT EXISTS audit_entity_seq ON audit(entity,seq)',
                'CREATE TABLE IF NOT EXISTS purchase_index(id TEXT PRIMARY KEY,kind TEXT NOT NULL,title TEXT NOT NULL,supplier TEXT NOT NULL,currency TEXT NOT NULL,total_cents INTEGER NOT NULL,updated_at TEXT NOT NULL,expires_at TEXT,parent_quote_id TEXT)',
                'CREATE INDEX IF NOT EXISTS purchases_recent ON purchase_index(updated_at DESC,id)',
                'CREATE INDEX IF NOT EXISTS purchases_parent ON purchase_index(parent_quote_id,kind)',
                "CREATE TABLE IF NOT EXISTS reconciliations(quote_id TEXT PRIMARY KEY REFERENCES quotes(id),state TEXT NOT NULL CHECK(state IN ('pending','checking','resolved','manual')),attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0),lease_token TEXT,lease_until DOUBLE PRECISION NOT NULL DEFAULT 0,next_attempt DOUBLE PRECISION NOT NULL DEFAULT 0,last_code TEXT NOT NULL DEFAULT '',updated TEXT NOT NULL)",
                'CREATE INDEX IF NOT EXISTS reconciliation_due ON reconciliations(state,next_attempt)',
            ]
            for sql in statements:
                db.execute(sql)
            additions = {'quotes': {'revoked_at': 'TEXT', 'declined_at': 'TEXT', 'decision_note': 'TEXT', 'reviewer': 'TEXT'},
                         'orders': {'capture_started_at': 'TEXT', 'simulation_scenario': "TEXT NOT NULL DEFAULT 'normal'",
                                    'approval_snapshot': 'TEXT', 'create_lease_until':'DOUBLE PRECISION NOT NULL DEFAULT 0',
                                    'create_attempts':'INTEGER NOT NULL DEFAULT 0', 'reconcile_lease_until':'DOUBLE PRECISION NOT NULL DEFAULT 0',
                                    'reconcile_token':'TEXT'}}
            for table, columns in additions.items():
                if self.postgres:
                    existing = {r['column_name'] for r in db.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?', (table,)).fetchall()}
                else:
                    existing = {r['name'] for r in db.execute(f'PRAGMA table_info({table})').fetchall()}
                for name, kind in columns.items():
                    if name not in existing:
                        db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
                        if name == 'capture_started_at':
                            db.execute("UPDATE orders SET capture_started_at='legacy-unknown' WHERE mode='sandbox' AND remote_id IS NOT NULL")
            from .core import now
            db.execute('INSERT OR IGNORE INTO schema_migrations(version,applied) VALUES(?,?)', (2, now()))
            if not db.execute('SELECT version FROM schema_migrations WHERE version=3').fetchone():
                for row in db.execute('SELECT * FROM quotes').fetchall():
                    body = json.loads(row['body'])
                    self.index(db, row['id'], 'quote', body, body.get('created_at', now()))
                for row in db.execute('SELECT * FROM drafts WHERE quote_id IS NULL').fetchall():
                    self.index(db, row['id'], 'draft', json.loads(row['body']), row['updated'])
                # Legacy settled records gain one receipt; original rows stay intact.
                from .core import packed
                for row in db.execute("SELECT q.body AS quote_body,o.remote_id,o.mode,o.body AS order_body FROM quotes q JOIN orders o ON q.id=o.quote_id WHERE o.status IN ('SIMULATED_PAID','SANDBOX_PAID')").fetchall():
                    q=json.loads(row['quote_body']); order=json.loads(row['order_body'])
                    if not q.get('items'):
                        continue
                    receipt=dict(id='SP-'+q['id'].upper(),quote_id=q['id'],order_id=row['remote_id'],
                        issued_at=order.get('verified_at',q['created_at']),mode=row['mode'],legacy_backfill=True,
                        title=q.get('title',q['items'][0]['title']),supplier=q.get('supplier',''),
                        currency=q['currency'],total_cents=q['total_cents'],fingerprint=q['fingerprint'],
                        items=q['items'],payment_verified=bool(order.get('payment_verified')))
                    db.execute('INSERT OR IGNORE INTO receipts(id,quote_id,order_id,body,created) VALUES(?,?,?,?,?)',
                        (receipt['id'],q['id'],row['remote_id'],packed(receipt),receipt['issued_at']))
                db.execute('INSERT INTO schema_migrations(version,applied) VALUES(?,?)', (3, now()))
            db.execute("""INSERT OR IGNORE INTO reconciliations(quote_id,state,updated)
                SELECT quote_id,CASE WHEN status IN ('SIMULATED_PAID','SANDBOX_PAID','SIMULATED_DECLINED') THEN 'resolved' ELSE 'pending' END,?
                FROM orders WHERE capture_started_at IS NOT NULL""",(now(),))
            db.execute('INSERT OR IGNORE INTO schema_migrations(version,applied) VALUES(?,?)',(4,now()))

    @staticmethod
    def index(db, key, kind, body, updated):
        total=body.get('total_cents',sum(x['quantity']*x['unit_cents'] for x in body.get('items',[]) if x.get('included',True)))
        title=body.get('title') or next((x['title'] for x in body.get('items',[]) if x.get('title')), '')
        db.execute('''INSERT INTO purchase_index(id,kind,title,supplier,currency,total_cents,updated_at,expires_at,parent_quote_id)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,supplier=excluded.supplier,
            currency=excluded.currency,total_cents=excluded.total_cents,updated_at=excluded.updated_at,expires_at=excluded.expires_at''',
            (key,kind,title,body.get('supplier',''),body.get('currency','USD'),total,updated,body.get('expires_at'),body.get('parent_quote_id')))

    @contextmanager
    def operation(self, key):
        """Reentrant per-thread, process-safe, released by OS/PG after a crash."""
        from .core import Problem
        name = hashlib.sha256(str(key).encode()).digest()
        if not self.postgres:key='stripe-'+str(int.from_bytes(name[:2],'big')%256)
        held = getattr(self._local, 'held', set())
        if key in held:
            yield
            return
        if not held and not self.operation_slots.acquire(timeout=.5):
            raise Problem('database_busy_retry', 503)
        owns_slot = not held
        deadline = time.monotonic() + 35
        handle = None
        locked = False
        try:
            if self.postgres:
                try:handle = self.pool.getconn(timeout=2) if self.pool else self.connect()
                except Exception:raise Problem('database_busy_retry',503) from None
                handle.autocommit = True
                lock_id = int.from_bytes(name[:8], 'big', signed=True)
                while time.monotonic() < deadline:
                    if handle.execute('SELECT pg_try_advisory_lock(%s) AS locked', (lock_id,)).fetchone()['locked']:
                        locked = True
                        break
                    time.sleep(.05)
            else:
                folder = Path(self.path).parent / (Path(self.path).name + '.locks')
                folder.mkdir(exist_ok=True)
                handle = open(folder / (key + '.lock'), 'a+b')
                if handle.tell() == 0:
                    handle.write(b'0'); handle.flush()
                while time.monotonic() < deadline:
                    try:
                        handle.seek(0)
                        if os.name == 'nt':
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                        break
                    except OSError:
                        time.sleep(.05)
            if not locked:
                raise Problem('operation_in_progress_retry_refresh', 409)
            self._local.held = held | {key}
            yield
        finally:
            self._local.held = held
            try:
                if handle is not None:
                    try:
                        if locked and self.postgres:
                            handle.execute('SELECT pg_advisory_unlock(%s)', (lock_id,))
                    except Exception:
                        # A lost connection already releases PostgreSQL's session
                        # lock. Cleanup must still release the local capacity slot.
                        try:handle.close()
                        except Exception:pass
                    finally:
                        if self.postgres:
                            try:
                                if not handle.closed:handle.autocommit=False
                            except Exception:
                                try:handle.close()
                                except Exception:pass
                            self.release(handle)
                        else:handle.close()
            finally:
                if owns_slot:
                    self.operation_slots.release()

    @staticmethod
    def audit(db, entity, action, data=None):
        from .core import now, packed
        db.execute('INSERT INTO audit(entity,action,created,data) VALUES(?,?,?,?)', (entity, action, now(), packed(data or {})))

    def analysis(self, key):
        from .core import Problem, digest
        with self.tx(read=True) as db:
            row = db.execute('SELECT body FROM analyses WHERE id=?', (key,)).fetchone()
        if not row:
            raise Problem('analysis_not_found', 404)
        value=json.loads(row['body'])
        if 'source' in value and 'source_sha256' in value:
            accepted={hashlib.sha256(value['source'].encode('utf-8')).hexdigest(),digest(value['source'])}
            if value['source_sha256'] not in accepted:
                raise Problem('source_integrity_mismatch',409)
        return value

    def quote(self, key):
        from .core import Problem, digest
        with self.tx(read=True) as db:
            row = db.execute('SELECT * FROM quotes WHERE id=?', (key,)).fetchone()
        if not row:
            raise Problem('quote_not_found', 404)
        value=json.loads(row['body'])
        if value.get('fingerprint') and value['fingerprint']!=digest({k:v for k,v in value.items() if k!='fingerprint'}):
            raise Problem('quote_integrity_mismatch',409)
        return {**value, **{k: row[k] for k in ('confirmed_at', 'confirm_fingerprint', 'revoked_at', 'declined_at', 'decision_note', 'reviewer')}}
