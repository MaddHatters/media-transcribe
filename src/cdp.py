"""Reusable async Chrome DevTools Protocol client via WebSocket."""
from __future__ import annotations

import asyncio
import json
import urllib.request
from typing import Any

try:
    import websockets
except ImportError:
    import types
    websockets = types.ModuleType("websockets")  # type: ignore[assignment]
    websockets.connect = None  # type: ignore[attr-defined]

from src.config import CDP_URL


class CDPClient:
    """Chrome DevTools Protocol client via WebSocket."""

    def __init__(self, cdp_url: str = CDP_URL):
        self._cdp_url = cdp_url
        self._ws = None
        self._msg_id = 0
        self._events: list[dict] = []

    async def connect(self) -> None:
        ws_url = self.get_ws_url(self._cdp_url)
        self._ws = await websockets.connect(
            ws_url, max_size=50 * 1024 * 1024, ping_interval=30,
        )

    async def disconnect(self) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def __aenter__(self) -> CDPClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.disconnect()

    async def _send(self, method: str, params: dict | None = None) -> dict:
        self._msg_id += 1
        mid = self._msg_id
        await self._ws.send(json.dumps({
            "id": mid, "method": method, "params": params or {},
        }))
        while True:
            resp = json.loads(await self._ws.recv())
            if resp.get("id") == mid:
                return resp
            if "method" in resp:
                self._events.append(resp)

    def drain_events(self, method: str | None = None) -> list[dict]:
        if method is None:
            events = self._events[:]
            self._events.clear()
            return events
        matched = [e for e in self._events if e.get("method") == method]
        self._events = [e for e in self._events if e.get("method") != method]
        return matched

    async def collect_events(self, duration: float) -> int:
        deadline = asyncio.get_event_loop().time() + duration
        count = 0
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=remaining)
                resp = json.loads(raw)
                if "method" in resp:
                    self._events.append(resp)
                    count += 1
            except asyncio.TimeoutError:
                break
        return count

    async def navigate(self, url: str, wait: float = 8.0) -> None:
        await self._send("Page.navigate", {"url": url})
        if wait > 0:
            await asyncio.sleep(wait)

    async def js(self, expression: str) -> Any:
        r = await self._send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        return r.get("result", {}).get("result", {}).get("value")

    async def click(self, x: float, y: float) -> None:
        await self._send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        await self._send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })

    async def key(self, key: str, code: str) -> None:
        await self._send("Input.dispatchKeyEvent", {
            "type": "keyDown", "key": key, "code": code,
        })
        await self._send("Input.dispatchKeyEvent", {
            "type": "keyUp", "key": key, "code": code,
        })

    async def move_mouse(self, x: float, y: float) -> None:
        await self._send("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": x, "y": y,
        })

    @staticmethod
    def get_ws_url(cdp_url: str = CDP_URL) -> str:
        data = urllib.request.urlopen(f"{cdp_url}/json", timeout=5).read()
        pages = json.loads(data)
        page = next(p for p in pages if p["type"] == "page")
        return page["webSocketDebuggerUrl"]
