"""No redirect replay in the HTTP transports shipped by the pinned Proxy."""

import aiohttp
import httpx
import requests


def install_no_redirects():
    if getattr(httpx.AsyncClient.send, "_dramaforge_no_redirects", False):
        return
    async_httpx = httpx.AsyncClient.send
    sync_httpx = httpx.Client.send
    requests_send = requests.Session.send
    aiohttp_request = aiohttp.ClientSession._request

    async def async_send(self, request, **kwargs):
        kwargs["follow_redirects"] = False
        return await async_httpx(self, request, **kwargs)

    def sync_send(self, request, **kwargs):
        kwargs["follow_redirects"] = False
        return sync_httpx(self, request, **kwargs)

    def session_send(self, request, **kwargs):
        kwargs["allow_redirects"] = False
        return requests_send(self, request, **kwargs)

    async def session_request(self, method, url, **kwargs):
        kwargs["allow_redirects"] = False
        return await aiohttp_request(self, method, url, **kwargs)

    async_send._dramaforge_no_redirects = True
    httpx.AsyncClient.send = async_send
    httpx.Client.send = sync_send
    requests.Session.send = session_send
    aiohttp.ClientSession._request = session_request
