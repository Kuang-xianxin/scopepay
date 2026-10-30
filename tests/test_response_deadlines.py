"""All response paths have a send deadline, including admission rejection."""
import asyncio
import pytest
from starlette.responses import JSONResponse
from scopepay.admission import AdmissionMiddleware


@pytest.mark.parametrize('path',['normal','rejected','invalid','upload_timeout'])
def test_stalled_error_and_normal_response_are_bounded(path):
    async def check():
        metrics=dict(requests=0,rejected=0,errors=0,active=0,max_active=0,total_ms=0)
        headers=[]
        async def receive():
            if path=='upload_timeout':await asyncio.sleep(3)
            return {'type':'http.request','body':b'{}','more_body':False}
        async def send(message):
            if message['type']=='http.response.start':headers.append(message['status'])
            await asyncio.Event().wait()
        async def app(scope,recv,out):
            if path=='upload_timeout':await recv()
            await JSONResponse({'error':'invalid_input'} if path=='invalid' else {'ok':True},status_code=422 if path=='invalid' else 200)(scope,recv,out)
        bound=AdmissionMiddleware(app,metrics,limit=0 if path=='rejected' else 1,deadline=.02,receive_timeout=.005)
        bound.send_timeout=.01
        task=asyncio.create_task(bound({'type':'http','path':'/api/test'},receive,send))
        await asyncio.sleep(.08)
        completed=task.done()
        if not completed:task.cancel()
        result=await asyncio.gather(task,return_exceptions=True)
        assert completed,'Response still blocked after its send deadline'
        assert isinstance(result[0],TimeoutError)
        assert headers==[{'normal':200,'invalid':422,'rejected':503,'upload_timeout':504}[path]]
        assert metrics['active']==0
        assert metrics['rejected']==int(path=='rejected')
    asyncio.run(check())


def test_partial_response_timeout_never_sends_second_headers():
    async def check():
        headers=[];m=dict(requests=0,rejected=0,errors=0,active=0,max_active=0,total_ms=0)
        async def receive():return {'type':'http.request','body':b''}
        async def send(msg):
            if msg['type']=='http.response.start':headers.append(msg['status'])
            else:await asyncio.Event().wait()
        async def app(scope,receive,send):await JSONResponse({'ok':True})(scope,receive,send)
        middleware=AdmissionMiddleware(app,m,deadline=.03);middleware.send_timeout=.01
        with pytest.raises(TimeoutError):await middleware({'type':'http','path':'/api/test'},receive,send)
        assert headers==[200] and m['active']==0
    asyncio.run(check())
