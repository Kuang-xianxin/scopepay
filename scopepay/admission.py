"""Bound API work for the full ASGI receive-to-final-send lifetime."""
import asyncio
import threading
import time

from starlette.responses import JSONResponse


class AdmissionMiddleware:
    def __init__(self, app, metrics, limit=24, deadline=120, receive_timeout=15, send_timeout=5):
        self.app,self.metrics,self.limit=app,metrics,limit
        self.deadline,self.receive_timeout=deadline,receive_timeout
        self.send_timeout=send_timeout
        self.guard=threading.Lock()

    async def __call__(self, scope, receive, send):
        if scope['type']!='http' or not scope.get('path','').startswith('/api/'):
            return await self.app(scope,receive,send)
        with self.guard:
            accepted=self.metrics['active']<self.limit
            if accepted:
                self.metrics['active']+=1
                self.metrics['requests']+=1
                self.metrics['max_active']=max(self.metrics['max_active'],self.metrics['active'])
            else:self.metrics['rejected']+=1
        if not accepted:
            # Rejections consume sockets/tasks too. Their entire reply must be
            # bounded even though they never acquired an admission slot.
            async with asyncio.timeout(self.send_timeout):
                return await JSONResponse({'error':'service_busy_retry'},503,headers={'Retry-After':'2'})(scope,receive,send)
        started=time.monotonic();response_started=False
        async def bounded_receive():
            return await asyncio.wait_for(receive(),timeout=self.receive_timeout)
        async def observed_send(message):
            nonlocal response_started
            if message['type']=='http.response.start':
                response_started=True
                if message['status']>=500:
                    with self.guard:self.metrics['errors']+=1
            await asyncio.wait_for(send(message),timeout=self.send_timeout)
        try:
            async with asyncio.timeout(self.deadline):
                await self.app(scope,bounded_receive,observed_send)
        except TimeoutError:
            if response_started:
                # A partial stream must abort; it cannot become a new JSON success.
                raise
            # Mark response start before awaiting the actual send. A timed-out
            # error response propagates; it must never trigger another header.
            async with asyncio.timeout(self.send_timeout):
                await JSONResponse({'error':'request_deadline_exceeded'},504)(scope,receive,observed_send)
        finally:
            with self.guard:
                self.metrics['active']-=1
                self.metrics['total_ms']+=round((time.monotonic()-started)*1000,2)
