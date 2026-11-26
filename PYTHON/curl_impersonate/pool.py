import asyncio
import inspect
import os
from collections import deque
from typing import (
    Awaitable,
    Callable,
    Deque,
    Iterable,
    List,
    Optional,
    TypeVar,
    Union,
)

from .client import Client
from .models import Response, Request, Settings


Input = TypeVar("Input")
Output = TypeVar("Output")
Callback = Callable[[Input, Output], Optional[Awaitable[None]]]


async def _call_callback(
        callback: Callback,
        item: Input,
        value: Output,
) -> None:
    try:
        result = callback(item, value)
        if inspect.isawaitable(result):
            await result
    except Exception as error:
        asyncio.get_running_loop().call_exception_handler({
            "message": "client pool callback failed",
            "exception": error,
            "callback": callback,
            "item": item,
        })


async def _run_with_callbacks(
        item: Input,
        operation: Awaitable[Output],
        on_result: Optional[Callback],
        on_error: Optional[Callback],
        return_exceptions: bool,
) -> Union[Output, Exception]:
    try:
        result = await operation
    except Exception as error:
        if on_error is not None:
            await _call_callback(on_error, item, error)
        if return_exceptions:
            return error
        raise

    if on_result is not None:
        await _call_callback(on_result, item, result)
    return result


async def _run_many(operations: Iterable[Awaitable[Output]]) -> List[Output]:
    tasks = []
    try:
        for operation in operations:
            tasks.append(asyncio.ensure_future(operation))
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        raise


class _BaseClientPool:
    """Shared client ownership and leasing for asynchronous pools."""

    def __init__(
            self,
            size: int,
            settings: Optional[Settings] = None,
            library_path: Optional[os.PathLike] = None,
    ):
        if size < 1:
            raise ValueError("pool size must be greater than zero")

        self._closed = False
        self._active = 0
        self._pending = 0
        self._clients: List[Client] = []
        self._available: Deque[Client] = deque()
        self._waiters: Deque[asyncio.Future] = deque()

        try:
            for _ in range(size):
                client = Client(library_path)
                self._clients.append(client)
                if settings is not None:
                    client.configure(settings)
                self._available.append(client)
        except Exception:
            self.close()
            raise

    @property
    def size(self) -> int:
        """Return the number of clients owned by the pool."""
        return len(self._clients)

    @property
    def active(self) -> int:
        """Return the number of clients currently executing work."""
        return self._active

    @property
    def pending(self) -> int:
        """Return the number of executing and queued operations."""
        return self._pending

    @property
    def running(self) -> bool:
        """Return whether an operation is executing or waiting for a client."""
        return self._pending > 0

    @property
    def closed(self) -> bool:
        """Return whether the pool has been closed."""
        return self._closed

    @property
    def clients(self) -> tuple[Client, ...]:
        """Return clients for configuration while the pool is idle."""
        return tuple(self._clients)

    def _offer_client(self, client: Client) -> None:
        if self._closed:
            return
        while self._waiters:
            waiter = self._waiters.popleft()
            if not waiter.done():
                waiter.set_result(client)
                return
        self._available.append(client)

    async def _acquire_client(self) -> Client:
        if self._closed:
            raise RuntimeError("client pool is closed")

        self._pending += 1
        if self._available:
            client = self._available.popleft()
            self._active += 1
            return client

        waiter = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        try:
            client = await waiter
            if self._closed:
                raise RuntimeError("client pool is closed")
            self._active += 1
            return client
        except BaseException:
            self._pending -= 1
            if waiter.done() and not waiter.cancelled():
                try:
                    client = waiter.result()
                except Exception:
                    pass
                else:
                    self._offer_client(client)
            else:
                waiter.cancel()
            raise

    def _release_client(self, client: Client) -> None:
        self._active -= 1
        self._pending -= 1
        self._offer_client(client)

    def close(self) -> None:
        """Wake queued operations and close every client owned by the pool."""
        if self._closed:
            return
        self._closed = True

        while self._waiters:
            waiter = self._waiters.popleft()
            if not waiter.done():
                waiter.set_exception(RuntimeError("client pool is closed"))

        for client in self._clients:
            client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.close()


class ClientPool(_BaseClientPool):
    """A fixed-size pool for independent HTTP requests."""

    async def execute(
            self,
            request: Request,
    ) -> Response:
        """Execute one request using the next available client."""
        client = await self._acquire_client()
        try:
            return await client.execute_async(request)
        finally:
            self._release_client(client)

    async def execute_all(
            self,
            requests: Iterable[Request],
            on_result: Optional[Callback] = None,
            on_error: Optional[Callback] = None,
            return_exceptions: bool = False,
    ) -> List[Union[Response, Exception]]:
        """
        Execute requests concurrently and preserve their input order.

        Sync and async callbacks are supported. ``on_result`` is invoked as
        soon as a request finishes. ``on_error`` is invoked if execution
        raises. Callback errors are reported to the event loop without changing
        the request result.

        With ``return_exceptions=True``, request exceptions are returned in
        their input positions and other requests continue. Otherwise the first
        exception cancels and awaits the remaining requests before it is
        re-raised. Task cancellation is always propagated.
        """
        return await _run_many(
            _run_with_callbacks(
                request,
                self.execute(request),
                on_result,
                on_error,
                return_exceptions,
            )
            for request in requests
        )


class ClientSessionPool(_BaseClientPool):
    """
    A client pool for dependent multi-request workflows.

    One client is leased to a workflow for its entire lifetime, so cookies,
    proxy settings, connections, and other client state remain attached to the
    same flow. At most ``size`` workflows run concurrently.
    """

    async def run(
            self,
            item: Input,
            flow: Callable[[Client, Input], Awaitable[Output]],
    ) -> Output:
        """Run one workflow with an exclusively leased client."""
        client = await self._acquire_client()
        try:
            return await flow(client, item)
        finally:
            self._release_client(client)

    async def run_all(
            self,
            items: Iterable[Input],
            flow: Callable[[Client, Input], Awaitable[Output]],
            *,
            on_result: Optional[Callback] = None,
            on_error: Optional[Callback] = None,
            return_exceptions: bool = False,
    ) -> List[Union[Output, Exception]]:
        """
        Run workflows concurrently and preserve the input order of results.

        Sync and async callbacks are supported. A workflow keeps its client
        until it returns or raises an exception. Callback errors are reported
        to the event loop without changing the workflow result.

        With ``return_exceptions=True``, workflow exceptions are returned in
        their input positions and other workflows continue. Otherwise the first
        exception cancels and awaits the remaining workflows before it is
        re-raised. Task cancellation is always propagated.
        """
        return await _run_many(
            _run_with_callbacks(
                item,
                self.run(item, flow),
                on_result,
                on_error,
                return_exceptions,
            )
            for item in items
        )
