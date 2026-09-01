"""Tests for src/cdp.CDPClient with mocked WebSocket."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.cdp import CDPClient


@pytest.fixture
def mock_ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    return ws


async def test_connect_gets_ws_url(mock_ws):
    """CDPClient.connect() fetches /json and connects to the first page's webSocketDebuggerUrl."""
    pages_json = json.dumps([{
        "type": "page",
        "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/ABC123",
    }]).encode()
    with patch("src.cdp.urllib.request.urlopen") as mock_urlopen, \
         patch("src.cdp.websockets.connect", new_callable=AsyncMock, return_value=mock_ws) as mock_connect:
        mock_urlopen.return_value.read.return_value = pages_json
        client = CDPClient()
        await client.connect()
        mock_connect.assert_called_once()


async def test_js_sends_runtime_evaluate(mock_ws):
    """CDPClient.js() sends Runtime.evaluate and returns the value."""
    mock_ws.recv = AsyncMock(return_value=json.dumps({
        "id": 1,
        "result": {"result": {"value": 42}},
    }))
    client = CDPClient.__new__(CDPClient)
    client._ws = mock_ws
    client._msg_id = 0
    result = await client.js("1 + 1")
    assert result == 42
    call_data = json.loads(mock_ws.send.call_args[0][0])
    assert call_data["method"] == "Runtime.evaluate"
    assert call_data["params"]["expression"] == "1 + 1"


async def test_click_dispatches_mouse_events(mock_ws):
    """CDPClient.click() sends mousePressed then mouseReleased."""
    mock_ws.recv = AsyncMock(side_effect=[
        json.dumps({"id": 1, "result": {}}),
        json.dumps({"id": 2, "result": {}}),
    ])
    client = CDPClient.__new__(CDPClient)
    client._ws = mock_ws
    client._msg_id = 0
    await client.click(100.0, 200.0)
    assert mock_ws.send.call_count == 2
    first_call = json.loads(mock_ws.send.call_args_list[0][0][0])
    assert first_call["params"]["type"] == "mousePressed"
    assert first_call["params"]["x"] == 100.0


async def test_navigate_sends_page_navigate(mock_ws):
    """CDPClient.navigate() sends Page.navigate and sleeps."""
    mock_ws.recv = AsyncMock(return_value=json.dumps({"id": 1, "result": {}}))
    client = CDPClient.__new__(CDPClient)
    client._ws = mock_ws
    client._msg_id = 0
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await client.navigate("https://example.com", wait=0.0)
    call_data = json.loads(mock_ws.send.call_args[0][0])
    assert call_data["method"] == "Page.navigate"
    assert call_data["params"]["url"] == "https://example.com"


async def test_key_dispatches_key_events(mock_ws):
    """CDPClient.key() sends keyDown then keyUp."""
    mock_ws.recv = AsyncMock(side_effect=[
        json.dumps({"id": 1, "result": {}}),
        json.dumps({"id": 2, "result": {}}),
    ])
    client = CDPClient.__new__(CDPClient)
    client._ws = mock_ws
    client._msg_id = 0
    await client.key("F11", "F11")
    assert mock_ws.send.call_count == 2


async def test_get_ws_url_returns_first_page():
    """get_ws_url() parses /json and returns the first page's WS URL."""
    pages_json = json.dumps([
        {"type": "background_page", "webSocketDebuggerUrl": "ws://bg"},
        {"type": "page", "webSocketDebuggerUrl": "ws://page1"},
    ]).encode()
    with patch("src.cdp.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.read.return_value = pages_json
        url = CDPClient.get_ws_url()
        assert url == "ws://page1"


async def test_send_buffers_events(mock_ws):
    """Events received during _send() are stored in _events."""
    mock_ws.recv = AsyncMock(side_effect=[
        json.dumps({"method": "Network.responseReceived", "params": {}}),
        json.dumps({"id": 1, "result": {}}),
    ])
    client = CDPClient.__new__(CDPClient)
    client._ws = mock_ws
    client._msg_id = 0
    client._events = []
    await client._send("Page.navigate", {"url": "https://example.com"})
    assert len(client._events) == 1
    assert client._events[0]["method"] == "Network.responseReceived"


def test_drain_events_all():
    """drain_events() with no filter returns all and clears."""
    client = CDPClient.__new__(CDPClient)
    client._events = [
        {"method": "Network.responseReceived", "params": {}},
        {"method": "Network.requestWillBeSent", "params": {}},
    ]
    events = client.drain_events()
    assert len(events) == 2
    assert len(client._events) == 0


def test_drain_events_filtered():
    """drain_events('Network.responseReceived') returns only matching events."""
    client = CDPClient.__new__(CDPClient)
    client._events = [
        {"method": "Network.responseReceived", "params": {"id": 1}},
        {"method": "Network.requestWillBeSent", "params": {"id": 2}},
        {"method": "Network.responseReceived", "params": {"id": 3}},
    ]
    matched = client.drain_events("Network.responseReceived")
    assert len(matched) == 2
    assert all(e["method"] == "Network.responseReceived" for e in matched)
    assert len(client._events) == 1
    assert client._events[0]["method"] == "Network.requestWillBeSent"


async def test_collect_events_duration(mock_ws):
    """collect_events() reads for specified duration."""
    import asyncio

    call_count = 0
    async def mock_recv():
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            return json.dumps({"method": f"Event.{call_count}", "params": {}})
        await asyncio.sleep(10)

    mock_ws.recv = mock_recv
    client = CDPClient.__new__(CDPClient)
    client._ws = mock_ws
    client._msg_id = 0
    client._events = []
    count = await client.collect_events(0.5)
    assert count >= 1
    assert len(client._events) == count
