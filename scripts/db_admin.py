"""Additive database tooling. Backup/restore/import never overwrite an existing file."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scopepay.core import Settings, Store, now, packed

TABLES = ('schema_migrations', 'analyses', 'quotes', 'orders', 'events', 'audit', 'drafts', 'receipts', 'simulated_captures', 'purchase_index', 'reconciliations')


def snapshot(store):
    result = {}
    with store.tx(read=True) as db:
        for table in TABLES:
            result[table] = [dict(r) for r in db.execute('SELECT * FROM '+table).fetchall()]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['backup', 'restore', 'migrate', 'import-sqlite', 'check'])
    parser.add_argument('--source')
    parser.add_argument('--target')
    args = parser.parse_args()
    settings = Settings.from_env()
    destination = settings.database_url or settings.db_path
    if args.action == 'backup':
        target = Path(args.target)
        if target.exists():
            raise SystemExit('Refusing to overwrite backup.')
        target.parent.mkdir(parents=True, exist_ok=True)
        if destination.startswith(('postgresql://', 'postgres://')):
            body = dict(format='ScopePay-logical-v2', created=now(), tables=snapshot(Store(destination)))
            target.write_text(packed(body), encoding='utf-8')
        else:
            with sqlite3.connect(destination) as src, sqlite3.connect(target) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise SystemExit('Backup integrity check failed.')
        print(json.dumps({'backup': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}))
    elif args.action == 'restore':
        target = Path(args.target)
        if target.exists():
            raise SystemExit('Restore target must be new; existing data is protected.')
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(f'file:{Path(args.source).as_posix()}?mode=ro', uri=True) as src, sqlite3.connect(target) as dst:
            if src.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise SystemExit('Source integrity check failed.')
            src.backup(dst)
        Store(str(target))
        print(json.dumps({'restored': str(target), 'integrity': 'ok'}))
    elif args.action == 'import-sqlite':
        dest = Store(destination)
        if not dest.postgres:
            raise SystemExit('Set private SCOPEPAY_DATABASE_URL for PostgreSQL import.')
        # Source is read only. Run additive migrations on a backup first if needed.
        with sqlite3.connect(f'file:{Path(args.source).as_posix()}?mode=ro', uri=True) as src:
            src.row_factory = sqlite3.Row
            tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            data = {t: [dict(r) for r in src.execute('SELECT * FROM '+t)] for t in TABLES if t in tables and t != 'schema_migrations'}
        # Shared transaction/identifier/content checks with the restore command.
        from scripts.migrate_postgres import import_rows
        try:
            import_rows(dest,data)
        finally:
            dest.close()
        print(json.dumps({'imported_counts': {t:len(r) for t,r in data.items()}, 'content_verified': True}))
    else:
        store = Store(destination)
        data = snapshot(store)
        print(json.dumps({'database':'postgresql' if store.postgres else 'sqlite','counts':{t:len(r) for t,r in data.items()}, 'migration':3}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Driver errors can contain DSNs. Do not print repr/config/exception text.
        print(json.dumps({'error_type':type(exc).__name__, 'message':'Database operation failed; credentials are not logged.'}))
        raise SystemExit(1)
