import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from scopepay.core import Problem


def test_real_sqlite_full_rolls_back_without_losing_original(factory):
    c=factory();store=c.app.state.store
    if store.postgres:pytest.skip('SQLite page quota fault; PG disk is coordinator owned')
    original=store.connect
    with store.tx() as db:db.execute('INSERT INTO analyses(id,body) VALUES(?,?)',('original','{}'))
    def constrained():
        db=original();pages=db.execute('PRAGMA page_count').fetchone()[0]
        db.execute('PRAGMA max_page_count='+str(pages));return db
    store.connect=constrained
    with pytest.raises(Problem) as exc:
        with store.tx() as db:db.execute('INSERT INTO analyses(id,body) VALUES(?,?)',('oversize','x'*2_000_000))
    assert exc.value.code=='database_write_failed_keep_state'
    store.connect=original
    with store.tx(read=True) as db:
        assert db.execute('SELECT COUNT(*) AS n FROM analyses').fetchone()['n']==1
        assert db.execute('SELECT body FROM analyses WHERE id=?',('original',)).fetchone()['body']=='{}'


def test_real_postgres_deadlock_is_bounded_and_recovers(factory):
    c=factory();store=c.app.state.store
    if not store.postgres:pytest.skip('PostgreSQL deadlock requires actual coordinator verify DB')
    with store.tx() as db:
        for key in ('a','b'):db.execute('INSERT INTO analyses(id,body) VALUES(?,?)',(key,'{}'))
    barrier=threading.Barrier(2)
    def contend(keys):
        try:
            with store.tx() as db:
                db.execute('UPDATE analyses SET body=? WHERE id=?',('first',keys[0]));barrier.wait(timeout=3)
                db.execute('UPDATE analyses SET body=? WHERE id=?',('second',keys[1]))
            return 'committed'
        except Problem as e:return e.code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(contend,[('a','b'),('b','a')]))
    assert sorted(results)==['committed','database_busy_retry']
    assert c.get('/api/ready').status_code==200
