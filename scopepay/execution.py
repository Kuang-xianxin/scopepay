"""Capacity follows actual synchronous work, even after HTTP cancellation."""
import inspect
import threading
from functools import wraps

from fastapi.routing import APIRoute
from .core import Problem


def bounded_routes(metrics,limit=8):
    slots=threading.BoundedSemaphore(limit)
    lock=threading.Lock()
    metrics.update(work_active=0,work_peak=0,work_rejected=0)

    class BoundedRoute(APIRoute):
        def __init__(self,path,endpoint,**kwargs):
            if not inspect.iscoroutinefunction(endpoint) and path not in ('/api/health','/api/metrics','/api/session'):
                original=endpoint
                @wraps(original)
                def endpoint(*args,**kw):
                    if not slots.acquire(blocking=False):
                        with lock:metrics['work_rejected']+=1
                        raise Problem('service_busy_retry',503)
                    with lock:
                        metrics['work_active']+=1
                        metrics['work_peak']=max(metrics['work_peak'],metrics['work_active'])
                    try:return original(*args,**kw)
                    finally:
                        with lock:metrics['work_active']-=1
                        slots.release()
            super().__init__(path,endpoint,**kwargs)
    return BoundedRoute
