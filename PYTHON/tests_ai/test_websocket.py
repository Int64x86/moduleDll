import pytest

from curl_impersonate import impersonate
from curl_impersonate.errors import NetworkError, WebSocketClosed, WebSocketTimeout
from curl_impersonate.models import Response
from curl_impersonate.websocket import WsContext


class FakeClient:
    def __init__(self, connect_response=None, native_responses=None):
        self.connect_response = connect_response or {
            "success": True,
            "state": "open",
        }
        self.native_responses = list(native_responses or [])
        self.calls = []

    def execute(self, request, *options):
        self.calls.append(request._native_call(*options))
        return Response(dict(self.connect_response))

    def _native_call(self, request):
        self.calls.append(request)
        return self.native_responses.pop(0)


def test_public_websocket_api_is_sync_only():
    assert impersonate.WsContext is WsContext
    assert not hasattr(impersonate.Client, "websocket_connect_async")
    assert not hasattr(WsContext, "send_async")
    assert not hasattr(WsContext, "monitor_async")


def test_ws_options_are_available_from_runtime():
    options = impersonate.WsOptions(receive_timeout_seconds=2, fail_on_error=False)

    assert options.connect_timeout_seconds == 10
    assert options.receive_timeout_seconds == 2
    assert options.fail_on_error is False


def test_sync_connect_raises_network_error_without_handler():
    client = FakeClient({"success": False, "error": "offline"})

    with pytest.raises(NetworkError, match="offline"):
        WsContext(client, "wss://example.test").connect()


def test_handler_receives_connect_error_without_exception():
    events = []
    client = FakeClient({"success": False, "error": "offline"})

    connection = WsContext(
        client,
        "wss://example.test",
        handler=lambda ctx, event: events.append((ctx, event)),
    ).connect()

    assert events[0][0] is connection
    assert events[0][1].type == impersonate.WsEventType.CONNECT
    assert events[0][1].is_error is True
    assert client.calls[0]["args"]["method"] == "GET"


def test_fail_on_error_false_returns_sync_error_event():
    client = FakeClient({"success": False, "error": "offline"})
    connection = WsContext(
        client,
        "wss://example.test",
        options=impersonate.WsOptions(fail_on_error=False),
    )

    connection.connect()

    assert connection._last_event.is_error is True


def test_send_uses_text_and_binary_native_payloads():
    client = FakeClient(native_responses=[
        {"success": True, "state": "open"},
        {"success": True, "state": "open"},
    ])
    connection = WsContext(client, "wss://example.test")
    connection.state = "open"

    text_event = connection.send("hello")
    binary_event = connection.send(b"\x00\xff")

    assert text_event.type == impersonate.WsEventType.SEND
    assert binary_event.type == impersonate.WsEventType.SEND
    assert client.calls[0]["args"]["type"] == "text"
    assert client.calls[0]["args"]["ws_send_fail_on_error"] is False
    assert client.calls[1]["args"]["type"] == "base64"
    assert client.calls[1]["args"]["payload"] == "AP8="


def test_event_code_is_curl_code_for_send_error():
    client = FakeClient(native_responses=[{
        "success": True,
        "was_error": True,
        "curl_code": 55,
        "error": "send failed",
    }])
    connection = WsContext(
        client,
        "wss://example.test",
        options=impersonate.WsOptions(fail_on_error=False),
    )

    event = connection.send("hello")

    assert event.curl_code == 55


def test_receive_timeout_raises_only_without_handler():
    timeout = {
        "success": True,
        "result_type": "timeout",
        "state": "open",
    }
    direct = WsContext(
        FakeClient(native_responses=[timeout]),
        "wss://example.test",
    )

    with pytest.raises(WebSocketTimeout):
        direct.recv()

    events = []
    handled = WsContext(
        FakeClient(native_responses=[timeout]),
        "wss://example.test",
        handler=lambda ctx, event: events.append(event),
    )
    event = handled.recv()

    assert event.is_timeout is True
    assert events == []


def test_closed_response_raises_websocket_closed():
    client = FakeClient(native_responses=[{
        "success": True,
        "result_type": "closed",
        "state": "closed",
        "close_code": 1000,
    }])
    connection = WsContext(client, "wss://example.test")

    with pytest.raises(WebSocketClosed) as raised:
        connection.recv()

    assert raised.value.event.close_code == 1000
    assert raised.value.event.curl_code == 1000


def test_event_retry_repeats_send_and_increments_counter():
    events = []
    client = FakeClient(native_responses=[
        {"success": True, "was_error": True, "error": "again"},
        {"success": True, "was_error": False},
    ])
    connection = WsContext(
        client,
        "wss://example.test",
        handler=lambda ctx, event: events.append(event),
    )

    first = connection.send("hello")
    second = first.retry()

    assert second.retries == 1
    assert len(events) == 2
    assert len(client.calls) == 2


def test_close_emits_closed_once_after_current_handler_returns():
    events = []
    client = FakeClient(native_responses=[{
        "success": True,
        "state": "closed",
        "close_code": 1000,
    }])

    def handler(ctx, event):
        events.append(event.type)
        if event.type == impersonate.WsEventType.RECV:
            ctx.close()

    connection = WsContext(client, "wss://example.test", handler=handler)
    connection._finish(impersonate.WsEvent(impersonate.WsEventType.RECV, data="hello"))
    connection.close()

    assert events == [impersonate.WsEventType.RECV, impersonate.WsEventType.CLOSED]
    assert connection.state == "closed"


def test_reconnect_inside_closed_handler_restores_connection():
    events = []
    client = FakeClient(native_responses=[
        {"success": True, "state": "closed", "close_code": 1000},
        {"success": True, "state": "open"},
    ])

    def handler(ctx, event):
        events.append(event.type)
        if event.type == impersonate.WsEventType.CLOSED:
            ctx.reconnect()

    connection = WsContext(client, "wss://example.test", handler=handler)
    connection.state = "open"
    connection.close()

    assert events == [impersonate.WsEventType.CLOSED, impersonate.WsEventType.CONNECT]
    assert connection.is_connected is True
    assert connection._closed_by_user is False
