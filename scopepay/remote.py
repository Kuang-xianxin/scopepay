"""Bound upstream bytes and elapsed time before decoding untrusted JSON."""
import json
import time
from .core import Problem


def bounded_response(client,method,url,*,limit=131072,deadline=25,**kwargs):
    started=time.monotonic();chunks=[];size=0
    with client.stream(method,url,**kwargs) as response:
        for chunk in response.iter_bytes(8192):
            size+=len(chunk)
            if size>limit:raise Problem('remote_response_too_large',502)
            if time.monotonic()-started>deadline:raise Problem('remote_response_deadline',504)
            chunks.append(chunk)
        # Keep the normal HTTPX response/status interface, with bounded content.
        response._content=b''.join(chunks)
        return response
