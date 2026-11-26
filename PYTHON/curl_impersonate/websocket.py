import base64
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Union

from .errors import NetworkError, WebSocketClosed, WebSocketError, WebSocketTimeout
from .models import (
    Get,
    Response,
    Retry,
    WsResponse,
    WsEventType,
    WsFrameType,
    WsOptions,
    _NativeResponse,
)


WebSocketHandler = Callable[["WsContext", "WsEvent"], Any]


@dataclass
class WsEvent:
    type: WsEventType
    data: Optional[Union[str, bytes]] = None
    is_error: bool = False
    is_timeout: bool = False
    error: str = ""
    retries: int = 0
    curl_code: int = 0
    close_code: int = 0
    close_reason: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)

    _retry: Optional[Callable[[int], "WsEvent"]] = field(
        default=None, repr=False, compare=False
    )

    @property
    def is_binary(self) -> bool:
        return isinstance(self.data, bytes)

    def text(self, encoding: str = "utf-8") -> str:
        """Return WebSocket message data as text."""
        if self.data is None:
            return ""

        if isinstance(self.data, bytes):
            return self.data.decode(encoding)

        return self.data

    def json(self) -> Any:
        """Parse WebSocket message data as JSON."""
        return json.loads(self.text())

    def retry(self) -> "WsEvent":
        """Retry the operation associated with this event."""
        if self._retry is None:
            raise WebSocketError(
                "This WebSocket event cannot be retried", self
            )

        return self._retry(self.retries + 1)



class WsContext:
    def __init__(
            self,
            client,
            url: str,
            handler: Optional[WebSocketHandler] = None,
            options: Optional[WsOptions] = None,
            headers=None,
    ):
        self.client = client
        self.url = url
        self.handler = handler
        self.options = options or WsOptions()
        self.headers = headers or {}
        self.state = "disconnected"
        self._closed_by_user = False
        self._last_event: Optional[WsEvent] = None
        self._handler_depth = 0
        self._pending_closed_event: Optional[WsEvent] = None
        self._closed_event_emitted = False

    @property
    def is_connected(self) -> bool:
        return self.state == "open"

    def connect(self) -> "WsContext":
        self._finish(self._connect_event())
        return self

    def _connect_event(self, retries: int = 0) -> WsEvent:
        request = Get(
            url=self.url,
            headers=self.headers,
            connect_timeout_seconds=self.options.connect_timeout_seconds,
            read_timeout_seconds=self.options.receive_timeout_seconds,
            fail_on_error=False,
            retry=Retry(),
        )
        try:
            response = self.client.execute(request)
        except Exception as error:
            response = Response({
                "success": False,
                "error": str(error),
                "network_error": True,
            })
        event = self._make_event(WsEventType.CONNECT, response, retries)
        event._retry = lambda count: self._finish(self._connect_event(count))
        return event

    def send(self, data: Union[str, bytes, dict, list]) -> WsEvent:
        if isinstance(data, (dict, list)):
            data = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return self._finish(self._send_event(data))

    def _send_event(self, data: Union[str, bytes], retries: int = 0) -> WsEvent:
        is_binary = isinstance(data, bytes)
        payload = base64.b64encode(data).decode("ascii") if is_binary else data
        response = self._native_response(
            "ws_send",
            {
                "payload": payload,
                "type": (
                    WsFrameType.BASE64.value
                    if is_binary else WsFrameType.TEXT.value
                ),
                "ws_send_fail_on_error": False,
            },
        )
        event = self._make_event(WsEventType.SEND, response, retries)
        event.data = data
        event._retry = lambda count: self._finish(self._send_event(data, count))
        return event

    def recv(self, timeout_seconds: Optional[int] = None) -> WsEvent:
        return self._finish(self._recv_event(timeout_seconds))

    def _recv_event(
            self,
            timeout_seconds: Optional[int] = None,
            retries: int = 0,
    ) -> WsEvent:
        timeout = (
            self.options.receive_timeout_seconds
            if timeout_seconds is None else timeout_seconds
        )
        response = self._native_response(
            "ws_recv",
            {"response_timeout": timeout},
            WsResponse,
        )
        event_type = WsEventType.RECV
        result_type = str(response.raw.get("result_type", "")).lower()
        native_type = str(response.raw.get("event_type", "")).lower()
        if result_type == "closed" or native_type == "closed":
            event_type = WsEventType.CLOSED
        event = self._make_event(event_type, response, retries)
        event.data = response.frame
        event._retry = lambda count: self._finish(
            self._recv_event(timeout_seconds, count)
        )
        return event

    def reconnect(self) -> WsEvent:
        return self._finish(self._reconnect_event())

    def _reconnect_event(self, retries: int = 0) -> WsEvent:
        response = self._native_response("ws_reconnect")
        event = self._make_event(WsEventType.CONNECT, response, retries)
        event._retry = lambda count: self._finish(self._reconnect_event(count))
        return event

    def close(self, code: int = 1000, reason: str = "") -> WsEvent:
        if self.state == "closed" and self._closed_event_emitted:
            return self._last_event or WsEvent(WsEventType.CLOSED)
        event = self._close_event(code, reason)
        self._closed_by_user = True
        self.state = "closed"
        return self._finish(event, raise_closed=event.is_error)

    def _close_event(self, code: int, reason: str) -> WsEvent:
        response = self._native_response(
            "ws_close", {"close_code": code, "reason": reason}
        )
        return self._make_event(WsEventType.CLOSED, response)

    def monitor(
            self,
            data: Optional[Union[str, bytes]] = None,
            handler: Optional[WebSocketHandler] = None,
    ) -> "WsContext":
        if handler is not None:
            self.handler = handler
        if data is not None:
            self.send(data)
        while not self._closed_by_user:
            event = self.recv()
            if event.type == WsEventType.CLOSED and not self.is_connected:
                break
        return self

    def _native_response(
            self,
            action: str,
            args: Optional[Mapping[str, Any]] = None,
            response_type: type[_NativeResponse] = _NativeResponse,
    ) -> _NativeResponse:
        try:
            return response_type(self.client._native_call({
                "action": action,
                "args": dict(args or {}),
            }))
        except Exception as error:
            return response_type({
                "success": False,
                "error": str(error),
                "network_error": True,
            })

    def _make_event(
            self,
            event_type: WsEventType,
            response: _NativeResponse,
            retries: int = 0,
    ) -> WsEvent:
        raw = response.raw
        result_type = str(raw.get("result_type", "")).lower()
        is_timeout = bool(raw.get("isTimeout", result_type == "timeout"))
        is_error = bool(raw.get(
            "isError",
            raw.get("was_error", not response.success),
        ))
        close_code = int(raw.get("close_code") or 0)
        curl_code = int(raw.get("curl_code") or 0)
        if event_type == WsEventType.CLOSED and close_code == 1006:
            is_error = True
        return WsEvent(
            type=event_type,
            is_error=is_error,
            is_timeout=is_timeout,
            error=response.error,
            retries=retries,
            close_code=close_code,
            close_reason=str(raw.get("close_reason", "")),
            curl_code=close_code if event_type == WsEventType.CLOSED else curl_code,
            raw=raw,
        )

    def _finish(self, event: WsEvent, raise_closed: bool = True) -> WsEvent:
        self._update_state(event)
        self._last_event = event
        if self.handler is not None:
            if event.is_timeout:
                return event
            if event.type == WsEventType.CLOSED:
                self._emit_closed(event)
            else:
                self._call_handler(event)
            return event
        if self.options.fail_on_error and (
                event.type != WsEventType.CLOSED or raise_closed
        ):
            self._raise(event)
        return event

    def _emit_closed(self, event: WsEvent) -> None:
        if self._closed_event_emitted:
            return
        self._closed_event_emitted = True
        if self._handler_depth:
            self._pending_closed_event = event
            return
        self._call_handler(event)

    def _call_handler(self, event: WsEvent) -> None:
        self._handler_depth += 1
        try:
            self.handler(self, event)
        finally:
            self._handler_depth -= 1
            if self._handler_depth == 0 and self._pending_closed_event is not None:
                pending = self._pending_closed_event
                self._pending_closed_event = None
                self._call_handler(pending)

    def _update_state(self, event: WsEvent) -> None:
        native_state = str(event.raw.get("state", "")).lower()
        if event.type == WsEventType.CLOSED:
            self.state = "closed"
        elif native_state:
            self.state = native_state
        elif event.type == WsEventType.CONNECT:
            self.state = "error" if event.is_error else "open"
        if event.type == WsEventType.CONNECT and not event.is_error:
            self._closed_by_user = False
            self._closed_event_emitted = False

    def _raise(self, event: WsEvent) -> None:
        if event.type == WsEventType.CLOSED:
            raise WebSocketClosed(event.error or "WebSocket is closed", event)
        if event.is_timeout:
            raise WebSocketTimeout(event.error or "WebSocket operation timed out", event)
        if not event.is_error:
            return
        if event.type == WsEventType.CONNECT or event.raw.get("network_error"):
            raise NetworkError(event.error, event)
        raise WebSocketError(event.error, event)

    def __iter__(self):
        while not self._closed_by_user:
            try:
                event = self.recv()
            except WebSocketTimeout:
                continue
            except WebSocketClosed:
                return
            if event.is_timeout:
                continue
            if event.type == WsEventType.CLOSED:
                return
            yield event.data

    def __enter__(self) -> "WsContext":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
