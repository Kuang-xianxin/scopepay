import asyncio
import pytest
from scopepay.admission import AdmissionMiddleware
from scopepay.core import Problem


def metrics():
    return dict(requests=0,rejected=0,errors=0,active=0,max_active=0,total_ms=0)


@pytest.mark.parametrize('phase',['upload','download'])
def test_slot_covers_slow_io_and_cancellation(phase):
    async def check():
        gate=asyncio.Event();entered=asyncio.Event();m=metrics();sent=[]
        async def receive():
            entered.set();await gate.wait();return {'type':'http.request','body':b'{}'}
        async def send(message):
            if message['type']=='http.response.body':entered.set();await gate.wait()
        async def app(scope,recv,out):
            if phase=='upload':await recv()
            await out({'type':'http.response.start','status':200,'headers':[]})
            await out({'type':'http.response.body','body':b'ok'})
        bound=AdmissionMiddleware(app,m,limit=1,deadline=2)
        scope={'type':'http','path':'/api/test'}
        task=asyncio.create_task(bound(scope,receive,send));await entered.wait()
        assert m['active']==1
        async def collect(message):sent.append(message)
        await bound(scope,receive,collect)
        assert sent[0]['status']==503 and m['rejected']==1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert m['active']==0
        gate.set();await bound(scope,receive,send);assert m['active']==0
    asyncio.run(check())


def test_slow_upload_times_out_and_releases():
    async def check():
        m=metrics();sent=[]
        async def receive():await asyncio.sleep(2)
        async def send(msg):sent.append(msg)
        async def app(scope,recv,out):await recv()
        await AdmissionMiddleware(app,m,deadline=.1,receive_timeout=.02)({'type':'http','path':'/api/test'},receive,send)
        assert sent[0]['status']==504 and m['active']==0
    asyncio.run(check())


def test_rollback_and_return_failure_preserve_business_error(factory,monkeypatch):
    c=factory();store=c.app.state.store
    class Broken:
        closed=False
        def execute(self,*args):pass
        def rollback(self):raise OSError('Synthetic rollback failure')
        def close(self):self.closed=True
    connection=Broken()
    class Pool:
        def getconn(self,**kwargs):return connection
        def putconn(self,conn):raise OSError('Synthetic pool return failure')
    with monkeypatch.context() as patch:
        patch.setattr(store,'pool',Pool())
        with pytest.raises(Problem) as exc:
            with store.tx():raise Problem('original_business_error',409)
        assert exc.value.code=='original_business_error' and connection.closed


def test_commit_disconnect_has_unknown_outcome(factory,monkeypatch):
    c=factory();store=c.app.state.store
    class Broken:
        def execute(self,*args):pass
        def commit(self):raise OSError('Synthetic response lost after commit')
        def rollback(self):raise OSError('Synthetic lost connection')
        def close(self):pass
    with monkeypatch.context() as patch:
        patch.setattr(store,'pool',None);patch.setattr(store,'connect',lambda:Broken())
        with pytest.raises(Problem) as exc:
            with store.tx():pass
        assert exc.value.code=='database_commit_unknown_refresh'
