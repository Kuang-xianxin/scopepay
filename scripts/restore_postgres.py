"""Restore a logical backup to a NEW schema in the verification database."""
import argparse
import json
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.migrate_postgres import dsn, import_rows
from scripts.db_admin import snapshot
from scopepay.core import Store, packed


def main():
    import psycopg
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--source',required=True);p.add_argument('--schema',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    if not re.fullmatch(r'restore_[a-z0-9_]{1,48}',args.schema):raise RuntimeError('Invalid restore schema')
    backup=json.loads(Path(args.source).read_text(encoding='utf-8'))
    if backup.get('format')!='ScopePay-logical-v2':raise RuntimeError('Invalid backup format')
    with psycopg.connect(dsn(args.config,test=True),connect_timeout=3) as conn:conn.execute('CREATE SCHEMA '+args.schema)
    store=Store(dsn(args.config,test=True,schema=args.schema))
    try:
        import_rows(store,backup['tables']);actual=snapshot(store)
        for t,rows in backup['tables'].items():
            if t!='schema_migrations' and sorted(map(packed,rows))!=sorted(map(packed,actual[t])):raise RuntimeError('Restore mismatch')
        result={'restore_schema':args.schema,'all_rows_equal':True,'counts':{t:len(r) for t,r in actual.items()},'destination':'verification database only'}
        Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
    finally:store.close()


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__,'error':'Restore failed; original workspace not modified.'}));raise SystemExit(1)
