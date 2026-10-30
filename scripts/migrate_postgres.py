"""Import a retained SQLite workspace to an empty dedicated PG DB, then switch config."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scopepay.core import ROOT, Store, packed, now
from scripts.db_admin import TABLES, snapshot


def dsn(config, test=False, schema=None):
    cfg=json.loads(Path(config).read_text(encoding='utf-8-sig'))
    base=f"postgresql://{quote(cfg['username'],safe='')}:{quote(cfg['password'],safe='')}@{cfg['host']}:{cfg['port']}/{cfg['test_database'] if test else cfg['database']}"
    return base+'?'+urlencode({'sslmode':cfg.get('sslmode','prefer'),**({'options':'-c search_path='+schema} if schema else {})})


def import_rows(store, data):
    if set(data)-set(TABLES):
        raise RuntimeError('Unsupported backup tables.')
    with store.tx() as db:
        for table in TABLES:
            if table=='schema_migrations':continue
            if db.execute('SELECT COUNT(*) AS n FROM '+table).fetchone()['n']:
                raise RuntimeError('Import requires an empty destination.')
        for table in TABLES:
            rows=data.get(table,[])
            if table=='schema_migrations':continue
            if store.postgres:
                allowed={r['column_name'] for r in db.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?',(table,)).fetchall()}
            else:
                allowed={r['name'] for r in db.execute('PRAGMA table_info('+table+')').fetchall()}
            columns=set(rows[0]) if rows else set()
            if not columns.issubset(allowed) or any(set(row)!=columns for row in rows):
                raise RuntimeError('Unsupported or inconsistent backup columns.')
            for row in rows:
                columns=list(row)
                db.execute(f'INSERT INTO {table}({",".join(columns)}) VALUES({",".join("?" for _ in columns)})',tuple(row[c] for c in columns))
            copied=[dict(r) for r in db.execute('SELECT * FROM '+table).fetchall()]
            compared=[{k:row[k] for k in columns} for row in copied]
            if sorted(map(packed,rows))!=sorted(map(packed,compared)):
                raise RuntimeError('Content mismatch during import.')
        if store.postgres:
            db.execute("SELECT setval(pg_get_serial_sequence('audit','seq'),COALESCE((SELECT MAX(seq) FROM audit),1),EXISTS(SELECT 1 FROM audit))")


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--source',required=True);p.add_argument('--record',required=True);args=p.parse_args()
    source=Path(args.source); record=Path(args.record);record.mkdir(parents=True,exist_ok=True)
    original=Store(str(source));data=snapshot(original)
    backup=record/'pre-postgres-migrated.db'
    if backup.exists():raise RuntimeError('Backup exists; choose a new record directory.')
    with sqlite3.connect(source) as src,sqlite3.connect(backup) as dst:
        src.backup(dst)
        assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    dest=Store(dsn(args.config))
    try:import_rows(dest,data)
    finally:dest.close()
    env=ROOT/'.env';prior=env.read_text(encoding='utf-8-sig') if env.exists() else ''
    private_backup=ROOT/'data'/('env-before-postgres-'+now().replace(':','-')+'.txt')
    private_backup.write_text(prior,encoding='utf-8')
    lines=[line for line in prior.splitlines() if not line.startswith(('SCOPEPAY_PG_CONFIG=','SCOPEPAY_DATABASE_URL='))]
    lines.append('SCOPEPAY_PG_CONFIG='+Path(args.config).as_posix())
    env.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    result={'migration':'SQLite to PostgreSQL','at':now(),'counts':{t:len(r) for t,r in data.items()},'all_original_columns_equal':True,
        'source_retained':str(source),'backup':str(backup),'backup_sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),'private_config_backup':str(private_backup),'destination_credentials':'not logged'}
    (record/'migration-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='private_config_backup'}))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__,'error':'Migration failed; source/config preserved unless import fully committed. No credentials logged.'}))
        raise SystemExit(1)
