import asyncio
import base64
import copy
import inspect
import logging
import os
import sys
import time
import weakref
from collections.abc import Iterable as IterableABC
from concurrent.futures import ThreadPoolExecutor
from threading import Condition, RLock, get_ident
from typing import Any, Coroutine, Iterable, List, Mapping, Optional, Union

from ._native import get_runtime
from .errors import error_from_response, LicenseError
from .models import (
    Cookie,
    ProxyType,
    Context,
    Request,
    Callbacks,
    Response,
    ResponseEncoding,
    Retry,
    SettingsResponse,
    Settings,
    _NativeResponse,
    Headers,
    WsResponse,
    WsFrameType,
    WsOptions,
    _headers_to_string,
    _parse_proxy,
)
from .websocket import WsContext, WebSocketHandler

logger = logging.getLogger("curl_impersonate")


class Client:
    _license_lock = RLock()
    _license_activated = False

    def __init__(self, library_path: Optional[os.PathLike] = None):
        """
        Create an HTTP client backed by the native cURL Impersonate runtime.

        Args:
            library_path: Optional path to ``moduledll.dll``.
        """
        self._runtime = get_runtime(library_path)
        self._state = Condition(RLock())
        self._error_lock = RLock()
        self._active_calls = 0
        self._closing = False
        self._handle = self._runtime.create_client()
        self._finalizer = weakref.finalize(
            self,
            Client._finalize_handle,
            self._runtime,
            self._handle,
        )
        self._runtime._clients.add(self)
        self.callbacks: Optional[Callbacks] = None
        self._async_lock = RLock()
        self._async_executor: Optional[ThreadPoolExecutor] = None
        self._async_worker_ident: Optional[int] = None
        self._last_error = ""
        self._last_url = ""

    @staticmethod
    def _finalize_handle(runtime, handle) -> None:
        """Release a native handle when Client is garbage-collected."""
        if runtime.dll and handle:
            runtime.dll.ci_client_destroy(handle)

    def _set_last_url(self, url: str) -> None:
        with self._error_lock:
            self._last_url = str(url or "")

    def _set_last_error(self, error: str) -> None:
        with self._error_lock:
            self._last_error = str(error or "")

    def _native_call(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Call native code while preventing concurrent handle destruction."""
        with self._state:
            if self._closing or not self._handle:
                error = RuntimeError("client is closed")
                self._set_last_error(str(error))
                raise error
            handle = self._handle
            self._active_calls += 1

        try:
            return self._runtime.call(handle, dict(request))
        except Exception as error:
            self._set_last_error(str(error))
            raise
        finally:
            with self._state:
                self._active_calls -= 1
                self._state.notify_all()

    def _call(
            self,
            action: str,
            args: Optional[Mapping[str, Any]] = None,
            response_type: type[_NativeResponse] = _NativeResponse,
    ) -> _NativeResponse:
        """Call one native action and raise the matching Python error on failure."""
        response = response_type(self._native_call(
            {"action": action, "args": dict(args or {})}
        ))
        if not response.success:
            self._set_last_error(response.error)
            raise error_from_response(response)
        self._set_last_error("")
        return response

    def execute(
            self,
            request: Request,
            _location: Optional[str] = None,
    ) -> Response:
        """
        Execute a request and return its response.

        Args:
            request: Request to execute.
        Returns:
            Response: The final response after retries and callbacks.

        Raises:
            RequestError: If the request fails and ``fail_on_error`` is enabled.
        """
        if _location is None:
            caller = inspect.currentframe().f_back
            _location = f"{os.path.basename(caller.f_code.co_filename)}:{caller.f_lineno}"
        retry = request.retry
        retry.attempt = 0
        retry.max_attempts = max(1, retry.max_attempts)
        if not retry.error_label:
            retry.error_label = _location
        callbacks = self._request_callbacks(request.callbacks)
        cookies = (
            self.get_cookies()
            if retry.rollback_cookies_on_error and retry.max_attempts > 1
            else None
        )
        response: Optional[Response] = None

        while True:
            retry.attempt += 1
            context = Context(request=request, retry=retry)
            self._run_callbacks(
                callbacks,
                "before_request",
                context,
                allow_flow_result=False,
            )
            request = context.request
            retry = context.retry

            if context.response is not None:
                response = context.response
            elif context.error:
                response = self._failed_response(None, context.error)
                context.response = response
                break
            else:
                response = Response(self._native_call(
                    request._native_call()
                ))
            context.response = response
            context.error = response.error if not response.success else ""

            error_before = context.error
            response_before = context.response
            after_result = self._run_callbacks(
                callbacks,
                "after_request",
                context,
            )
            request = context.request
            retry = context.retry
            if context.response is not response_before:
                response = context.response
                if context.error == error_before:
                    context.error = response.error if not response.success else ""
            if context.error:
                response = self._failed_response(response, context.error)
                context.response = response

            if after_result is True:
                break
            if after_result is False:
                continue

            error_result = None
            if not response.success:
                error_before = context.error
                response_before = context.response
                error_result = self._run_callbacks(callbacks, "on_error", context)
                request = context.request
                retry = context.retry
                if context.response is not response_before:
                    response = context.response
                    if context.error == error_before:
                        context.error = response.error if not response.success else ""
                if context.error:
                    response = self._failed_response(response, context.error)
                    context.response = response

            if error_result is True:
                break
            if error_result is False:
                continue

            if response.success or retry.attempt >= retry.max_attempts:
                break

            if retry.log_retry_errors:
                logger.warning(self._format_error(response.error, retry))
            if not response.success and cookies is not None:
                self.set_cookies(cookies)
            if retry.delay_ms > 0:
                delay_ms = retry.delay_ms
                if retry.exponential_backoff:
                    delay_ms *= 2 ** (retry.attempt - 1)
                time.sleep(delay_ms / 1000)

        if not response.success:
            response = self._failed_response(
                response,
                self._format_error(response.error, retry),
            )
            self._set_last_error(response.error)
        else:
            self._set_last_error("")
            self._set_last_url(response.url)
        if not response.success and request.fail_on_error:
            raise error_from_response(response)
        return response

    def execute_async(
            self,
            request: Request,
    ) -> Coroutine[Any, Any, Response]:
        """
        Return an awaitable request without blocking the asyncio event loop.

        One client runs asynchronous requests in submission order. Create
        separate Client instances for parallel network requests.

        Args:
            request: Request to execute.
        Returns:
            Coroutine: Await it to receive Response or raise the same
                exception as execute(). Cancelling it cancels the native request.
        """
        caller = inspect.currentframe().f_back
        location = f"{os.path.basename(caller.f_code.co_filename)}:{caller.f_lineno}"
        request_snapshot = copy.deepcopy(request)

        async def run() -> Response:
            with self._async_lock:
                with self._state:
                    if self._closing or not self._handle:
                        raise RuntimeError("client is closed")
                if self._async_executor is None:
                    self._async_executor = ThreadPoolExecutor(
                        max_workers=1,
                        thread_name_prefix="curl-impersonate",
                    )
                executor = self._async_executor

            loop = asyncio.get_running_loop()
            concurrent_worker = executor.submit(
                self._execute_async_worker,
                request_snapshot,
                location,
            )
            worker = asyncio.wrap_future(concurrent_worker, loop=loop)
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                if not concurrent_worker.cancel():
                    self.cancel()
                    try:
                        await asyncio.shield(worker)
                    except Exception:
                        pass
                raise

        return run()

    def _execute_async_worker(
            self,
            request: Request,
            location: str,
    ) -> Response:
        """Execute one asyncio request in the client's worker thread."""
        with self._async_lock:
            self._async_worker_ident = get_ident()
        try:
            return self.execute(request, _location=location)
        finally:
            with self._async_lock:
                self._async_worker_ident = None
            if self._closing:
                self._destroy_handle()

    def set_callbacks(self, callbacks: Optional[Callbacks]) -> None:
        """
        Set callbacks applied to every request made by this client.

        Args:
            callbacks: Callbacks to register, or None to clear them.
        """
        self.callbacks = callbacks

    def _request_callbacks(
            self,
            local: Optional[Callbacks],
    ) -> List[Callbacks]:
        """Combine request-local and client-wide callbacks."""
        callbacks = [local] if local is not None else []
        if self.callbacks and (
                local is None or local.use_global_callbacks
        ):
            callbacks.append(self.callbacks)
        return callbacks

    @staticmethod
    def _run_callbacks(
            callbacks: Iterable[Callbacks],
            name: str,
            context: Context,
            allow_flow_result: bool = True,
    ) -> Optional[bool]:
        """Run callbacks in order and stop at the first allowed flow result."""
        for callbacks_option in callbacks:
            callback = getattr(callbacks_option, name)
            if callback:
                try:
                    callback_result = callback(context)
                except Exception as error:
                    context.fail(f"({name}) {error}")
                    return True
                if allow_flow_result and callback_result is not None:
                    return callback_result
        return None

    @staticmethod
    def _failed_response(
            response: Optional[_NativeResponse],
            error: str,
    ) -> _NativeResponse:
        """Return a response copy marked as failed with the supplied error."""
        raw = dict(response.raw) if response else {"response": {}}
        raw["success"] = False
        raw["error"] = error
        raw.setdefault("error_type", "RequestError")
        return type(response)(raw) if response else Response(raw)

    @staticmethod
    def _format_error(error: str, retry: Retry) -> str:
        """Add the BAS-compatible request and attempt prefix to an error."""
        error = str(error or "").strip()
        if not error or error.startswith("[cUrl Impersonate"):
            return error
        suffix = ""
        if retry:
            suffix = [retry.error_label]
            if retry.max_attempts > 1:
                suffix.append(f"{retry.attempt}/{retry.max_attempts}")
        prefix = "[cUrl Impersonate"
        if suffix:
            prefix += ", " + ", ".join(suffix)
        return f"{prefix}] {error}"

    def configure(self, settings: Settings, prompt_for_license: bool = True) -> SettingsResponse:
        """
        Apply client-wide runtime settings.

        Args:
            settings: Browser preset, license, DNS, certificate, and profile settings.
            prompt_for_license: Prompt for a key when activation is required.

        Returns:
            SettingsResponse: Applied preset, profile, and license state.
        """
        if not Client._license_activated:
            with Client._license_lock:
                if not Client._license_activated:
                    while True:
                        try:
                            result = self._call(
                                "set_settings",
                                settings._native(),
                                SettingsResponse,
                            )
                            Client._license_activated = True
                            return result

                        except LicenseError as e:
                            if (
                                    not prompt_for_license
                                    or "Not activated" not in str(e)
                            ):
                                raise

                            print(Client._format_error(
                                f'{e}\n'
                                'Action "impersonate.Configure" requires a valid license key.\n'
                                'You can buy a license key here: https://cdn.fundata.fun/license/\n'
                                'Enter your license key:',
                                None,
                            ))

                            try:
                                settings.license_key = input().strip()
                            except EOFError:
                                raise e from None

        return self._call(
            "set_settings",
            settings._native(),
            SettingsResponse,
        )

    def set_proxy(
            self,
            server: str,
            port: int = None,
            proxy_type: ProxyType = ProxyType.HTTP,
            username: str = "",
            password: str = "",
    ) -> None:
        """
        Configure the proxy used by requests with ``use_proxy=True``.

        Supports HTTP, HTTPS, SOCKS4, SOCKS4A, SOCKS5, and SOCKS5A proxies.

        The proxy can be specified using separate arguments or a complete
        proxy string.

        Supported proxy string formats:
            host:port
            host:port:username:password
            username:password@host:port
            socks5://username:password@host:port
            socks5a://host:port

        Args:
            server: Proxy hostname or a complete proxy string.
            port: Proxy port. If omitted, parsed from server.
            proxy_type: Default proxy protocol if not specified in server.
            username: Optional username. Overrides parsed credentials when
                both username and password are provided.
            password: Optional password. Overrides parsed credentials when
                both username and password are provided.
        """
        if port is None:
            server, port, parsed_type, parsed_user, parsed_pass = _parse_proxy(server)

            if parsed_type is not None:
                proxy_type = parsed_type

            if username and password:
                parsed_user, parsed_pass = username, password

            username, password = parsed_user, parsed_pass

        self._call("set_proxy", {
            "server": server,
            "Port": port,
            "type": proxy_type,
            "name": username,
            "password": password,
        })

    def set_request_headers(self, headers: Headers) -> None:
        """
        Set the HTTP request headers.

        Args:
            headers: Headers to include in the HTTP request.

        """
        self._call("set_request_header", {"rawHeaders": _headers_to_string(headers)})

    def clear_request_headers(self) -> None:
        """
        Remove all headers stored on this client.

        """
        self._call("clear_request_headers")

    def get_cookies(self) -> Any:
        """
        Return cookies currently stored on this client.

        Returns:
            Any: Native cookie JSON data.
        """
        return self._call("get_cookies").raw.get("value", {}).get("cookies", [])

    def set_cookies(
            self,
            cookies: Union[str, Mapping, Iterable, Cookie],
            rewrite: bool = True,
    ) -> None:
        """
        Store cookies on this client.

        Args:
            cookies: A single Cookie, an iterable of Cookie objects,
                or native cookie JSON data.
            rewrite: Replace existing cookies when True; otherwise merge them.
        """
        if isinstance(cookies, Cookie):
            cookies = [cookies]

        if not isinstance(cookies, (str, Mapping)) and isinstance(cookies, IterableABC):
            cookies = list(cookies)

            if all(isinstance(cookie, Cookie) for cookie in cookies):
                cookies = {"cookies": [cookie._native() for cookie in cookies]}

            elif any(isinstance(cookie, Cookie) for cookie in cookies):
                raise TypeError("Cannot mix Cookie objects with other cookie formats")

        self._call("set_cookies", {
            "json_cookies": cookies,
            "rewrite": rewrite,
        })

    def reset(self) -> None:
        """
        Reset native client state, including cookies and stored headers.

        """
        self._call("reset")

    def get_response_status(self) -> int:
        """
        Return the HTTP status code of the latest response.

        Returns:
            int: Latest response status, or 0 when unavailable.
        """
        return int(self._call("get_response_status").raw.get("value", 0))

    def get_response_headers(self) -> str:
        """
        Return headers from the latest response.

        Returns:
            str: Raw response headers.
        """
        return str(self._call("get_response_headers").raw.get("value", ""))

    def get_response_header(self, name: str, index: int = -1) -> str:
        """
        Return one header from the latest response.

        Args:
            name: Header name.
            index: Occurrence index when the header appears multiple times.

        Returns:
            str: Header value, or an empty string when not found.
        """
        return str(self._call("get_response_header", {
            "name": name,
            "index": index,
        }).raw.get("value", ""))

    def get_response_content(
            self,
            encoding: ResponseEncoding = ResponseEncoding.AUTO,
            as_json: bool = False,
    ) -> Any:
        """
        Return the body of the latest response.

        Args:
            encoding: Decoding applied to the body.
            as_json: Parse the body as JSON.

        Returns:
            Any: Decoded body text, Base64 text, or parsed JSON value.
        """
        return self._call("get_response_content", {
            "encoding": encoding,
            "ContentAsJson": as_json,
        }).raw.get("value")

    def wasError(self) -> bool:
        """
        Return whether the latest client operation failed.

        Returns:
            bool: True when lastError() is not empty.
        """
        with self._error_lock:
            return bool(self._last_error)

    def lastError(self) -> str:
        """
        Return the formatted error from the latest failed client operation.

        Returns:
            str: Error text, or an empty string after a successful operation.
        """
        with self._error_lock:
            return self._last_error

    def lastUrl(self) -> str:
        """
        Return the effective URL of the latest successful HTTP request.

        Returns:
            str: Final URL after redirects, or an empty string before the
                first successful request.
        """
        with self._error_lock:
            return self._last_url

    def websocket_send(self, payload: Union[str, bytes]) -> None:
        """
        Send a text or binary frame through the active WebSocket connection.

        Args:
            payload: Text payload or binary bytes.
        """
        if isinstance(payload, bytes):
            self._call("ws_send", {
                "payload": base64.b64encode(payload).decode("ascii"),
                "type": WsFrameType.BASE64,
            })
            return
        self._call("ws_send", {"payload": payload, "type": WsFrameType.TEXT})

    def websocket_connect(
            self,
            url: str,
            handler: Optional[WebSocketHandler] = None,
            options: Optional[WsOptions] = None,
            *,
            headers=None,
    ) -> WsContext:
        """Create a WebSocket connection using a small WebSocket-only API."""
        return WsContext(
            self,
            url,
            handler=handler,
            options=options,
            headers=headers,
        ).connect()

    def websocket_receive(self, timeout_seconds: int = 5) -> WsResponse:
        """
        Receive one frame from the active WebSocket connection.

        Args:
            timeout_seconds: Maximum time to wait for a frame.

        Returns:
            WsResponse: The received frame and its metadata. Binary frames are
                decoded from native Base64 and returned as bytes.
        """
        return self._call(
            "ws_recv",
            {"response_timeout": timeout_seconds},
            WsResponse,
        )

    def cancel(self) -> None:
        """Request cancellation of the current native call on this client."""
        with self._state:
            if not self._handle:
                return
            handle = self._handle
            self._active_calls += 1
        try:
            self._runtime.dll.ci_client_cancel(handle)
        finally:
            with self._state:
                self._active_calls -= 1
                self._state.notify_all()

    def close(self) -> None:
        """Cancel pending asynchronous work and release the native client."""
        with self._async_lock:
            if self._closing:
                return
            self._closing = True
            executor = self._async_executor
            self._async_executor = None
            called_from_worker = self._async_worker_ident == get_ident()

        self.cancel()
        if executor:
            executor.shutdown(
                wait=not called_from_worker,
                cancel_futures=True,
            )
        if not called_from_worker:
            self._destroy_handle()

    def _destroy_handle(self) -> None:
        """Wait for native calls and destroy the client handle once."""
        with self._state:
            while self._active_calls:
                self._state.wait()
            handle = self._handle
            self._handle = None
        if handle:
            self._finalizer.detach()
            if self._runtime.dll:
                self._runtime.dll.ci_client_destroy(handle)

    def __enter__(self):
        """Return this client for use with a context manager."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Close this client when leaving a context manager."""
        self.close()
