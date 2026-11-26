import asyncio

import pytest

import curl_impersonate
from curl_impersonate import impersonate
from curl_impersonate import pool as pool_module


class FakeClient:
    clients = []
    active = 0
    max_active = 0

    def __init__(self, library_path=None):
        self.library_path = library_path
        self.settings = None
        self.proxy = None
        self.closed = False
        self.calls = []
        self.clients.append(self)

    def configure(self, settings):
        self.settings = settings

    def set_proxy(self, proxy):
        self.proxy = proxy

    async def execute_async(self, request):
        self.calls.append(request)
        type(self).active += 1
        type(self).max_active = max(type(self).max_active, type(self).active)
        try:
            await asyncio.sleep(0.01)
            return request.url
        finally:
            type(self).active -= 1

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    FakeClient.clients = []
    FakeClient.active = 0
    FakeClient.max_active = 0
    monkeypatch.setattr(pool_module, "Client", FakeClient)


def test_pool_executes_up_to_size_and_preserves_order():
    async def run():
        settings = impersonate.Settings(impersonation_preset="chromeLastWin10")
        requests = [impersonate.Get(url=f"https://example.org/{index}")
                    for index in range(5)]

        async with impersonate.ClientPool(size=2, settings=settings) as clients:
            assert clients.size == 2
            responses = await clients.execute_all(requests)

        assert responses == [request.url for request in requests]
        assert FakeClient.max_active == 2
        assert all(client.settings is settings for client in FakeClient.clients)
        assert all(client.closed for client in FakeClient.clients)

    asyncio.run(run())


def test_pool_reuses_client_after_request_error():
    class FailingClient(FakeClient):
        async def execute_async(self, request):
            if str(request.url).endswith("fail"):
                raise RuntimeError("request failed")
            return request.url

    pool_module.Client = FailingClient

    async def run():
        async with impersonate.ClientPool(size=1) as clients:
            with pytest.raises(RuntimeError, match="request failed"):
                await clients.execute(impersonate.Get(url="https://example.org/fail"))
            response = await clients.execute(
                impersonate.Get(url="https://example.org/success")
            )
            assert response == impersonate.Get(
                url="https://example.org/success"
            ).url

    asyncio.run(run())


def test_pool_exposes_read_only_clients_for_configuration():
    clients = impersonate.ClientPool(size=2)
    proxies = ["proxy-1.example:8080", "proxy-2.example:8080"]

    for client, proxy in zip(clients.clients, proxies):
        client.set_proxy(proxy)

    assert isinstance(clients.clients, tuple)
    assert [client.proxy for client in clients.clients] == proxies
    with pytest.raises(AttributeError):
        clients.clients = ()
    clients.close()


def test_pool_preserves_request_owned_options():
    async def run():
        requests = [
            impersonate.Get(
                url="https://example.org/0",
                retry=impersonate.Retry(max_attempts=2),
            ),
            impersonate.Get(
                url="https://example.org/1",
                response=impersonate.ResponseOptions(
                    include_redirect_headers=True,
                ),
            ),
        ]

        async with impersonate.ClientPool(size=2) as clients:
            await clients.execute_all(requests)

            calls = [call for client in clients.clients for call in client.calls]
            assert {call.url for call in calls} == {request.url for request in requests}
            assert requests[0].retry.max_attempts == 2
            assert requests[1].response.include_redirect_headers is True

    asyncio.run(run())


def test_request_defaults_are_independent():
    async def run():
        first = impersonate.Get(url="https://example.org/first")
        second = impersonate.Get(url="https://example.org/second")
        first.retry.max_attempts = 4

        async with impersonate.ClientPool(size=1) as clients:
            await clients.execute_all([first, second])

        assert second.retry.max_attempts == 1

    asyncio.run(run())


def test_execute_all_reports_results_as_they_finish():
    releases = {}

    class ControlledClient(FakeClient):
        async def execute_async(self, request):
            await releases[request.url].wait()
            return request.url

    pool_module.Client = ControlledClient

    async def run():
        requests = [
            impersonate.Get(url="https://example.org/first"),
            impersonate.Get(url="https://example.org/second"),
        ]
        for request in requests:
            releases[request.url] = asyncio.Event()

        completed = []
        async with impersonate.ClientPool(size=2) as clients:
            task = asyncio.create_task(clients.execute_all(
                requests,
                on_result=lambda request, response: completed.append(
                    (request.url, response)
                ),
            ))
            while clients.active < 2:
                await asyncio.sleep(0)

            assert clients.running
            releases[requests[1].url].set()
            while not completed:
                await asyncio.sleep(0)

            assert completed == [(requests[1].url, requests[1].url)]
            assert not task.done()

            releases[requests[0].url].set()
            responses = await task
            assert responses == [request.url for request in requests]
            assert clients.active == 0
            assert clients.pending == 0
            assert not clients.running

        assert clients.closed

    asyncio.run(run())


def test_running_includes_requests_waiting_for_a_client():
    releases = {
        "https://example.org/first": asyncio.Event(),
        "https://example.org/second": asyncio.Event(),
    }

    class ControlledClient(FakeClient):
        async def execute_async(self, request):
            await releases[str(request.url)].wait()
            return request.url

    pool_module.Client = ControlledClient

    async def run():
        requests = [impersonate.Get(url=url) for url in releases]
        states = []

        async with impersonate.ClientPool(size=1) as clients:
            task = asyncio.create_task(clients.execute_all(
                requests,
                on_result=lambda request, response: states.append(
                    (request.url, clients.pending, clients.running)
                ),
            ))
            while clients.pending < 2:
                await asyncio.sleep(0)

            releases[str(requests[0].url)].set()
            while not states:
                await asyncio.sleep(0)

            assert states[0] == (requests[0].url, 1, True)
            releases[str(requests[1].url)].set()
            await task

    asyncio.run(run())


def test_close_wakes_request_waiting_for_a_client():
    release = asyncio.Event()

    class ControlledClient(FakeClient):
        async def execute_async(self, request):
            await release.wait()
            return request.url

    pool_module.Client = ControlledClient

    async def run():
        clients = impersonate.ClientPool(size=1)
        first = asyncio.create_task(clients.execute(
            impersonate.Get(url="https://example.org/first")
        ))
        while clients.active < 1:
            await asyncio.sleep(0)

        waiting = asyncio.create_task(clients.execute(
            impersonate.Get(url="https://example.org/waiting")
        ))
        while clients.pending < 2:
            await asyncio.sleep(0)

        clients.close()
        with pytest.raises(RuntimeError, match="pool is closed"):
            await waiting

        release.set()
        await first
        assert clients.pending == 0

    asyncio.run(run())


def test_execute_all_cancels_and_awaits_siblings_after_error():
    slow_started = asyncio.Event()
    slow_cancelled = asyncio.Event()

    class FailingClient(FakeClient):
        async def execute_async(self, request):
            if str(request.url).endswith("fail"):
                await slow_started.wait()
                raise RuntimeError("request failed")

            slow_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                slow_cancelled.set()
                raise

    pool_module.Client = FailingClient

    async def run():
        async with impersonate.ClientPool(size=2) as clients:
            with pytest.raises(RuntimeError, match="request failed"):
                await clients.execute_all([
                    impersonate.Get(url="https://example.org/fail"),
                    impersonate.Get(url="https://example.org/slow"),
                ])

            assert slow_cancelled.is_set()
            assert clients.active == 0
            assert clients.pending == 0

    asyncio.run(run())


def test_execute_all_returns_exceptions_in_input_order():
    class FailingClient(FakeClient):
        async def execute_async(self, request):
            if str(request.url).endswith("fail"):
                raise RuntimeError("request failed")
            return request.url

    pool_module.Client = FailingClient

    async def run():
        completed = []
        failed = []
        requests = [
            impersonate.Get(url="https://example.org/first"),
            impersonate.Get(url="https://example.org/fail"),
            impersonate.Get(url="https://example.org/last"),
        ]

        async with impersonate.ClientPool(size=3) as clients:
            results = await clients.execute_all(
                requests,
                on_result=lambda request, result: completed.append(result),
                on_error=lambda request, error: failed.append(
                    (request.url, error)
                ),
                return_exceptions=True,
            )

            assert clients.active == 0
            assert clients.pending == 0

        assert results[0] == requests[0].url
        assert isinstance(results[1], RuntimeError)
        assert str(results[1]) == "request failed"
        assert results[2] == requests[2].url
        assert completed == [requests[0].url, requests[2].url]
        assert failed[0][0] == requests[1].url
        assert failed[0][1] is results[1]

    asyncio.run(run())


def test_callback_errors_do_not_change_operation_results():
    class FailingClient(FakeClient):
        async def execute_async(self, request):
            if str(request.url).endswith("fail"):
                raise RuntimeError("request failed")
            return request.url

    pool_module.Client = FailingClient

    async def run():
        completed = []
        callback_errors = []

        asyncio.get_running_loop().set_exception_handler(
            lambda loop, context: callback_errors.append(context)
        )

        async def on_result(request, response):
            await asyncio.sleep(0)
            completed.append(response)
            raise ValueError("result callback failed")

        async with impersonate.ClientPool(size=1) as clients:
            results = await clients.execute_all([
                impersonate.Get(url="https://example.org/success"),
            ], on_result=on_result)
            assert results == [impersonate.Get(
                url="https://example.org/success"
            ).url]
            assert completed == results

            def on_error(request, error):
                raise ValueError("error callback failed")

            with pytest.raises(RuntimeError, match="request failed"):
                await clients.execute_all([
                    impersonate.Get(url="https://example.org/fail"),
                ], on_error=on_error)

        assert [str(context["exception"]) for context in callback_errors] == [
            "result callback failed",
            "error callback failed",
        ]

    asyncio.run(run())


def test_pool_rejects_invalid_size():
    with pytest.raises(ValueError, match="greater than zero"):
        impersonate.ClientPool(size=0)


def test_closed_pool_rejects_requests():
    async def run():
        clients = impersonate.ClientPool(size=1)
        clients.close()
        with pytest.raises(RuntimeError, match="pool is closed"):
            await clients.execute(impersonate.Get())

    asyncio.run(run())


def test_client_pool_is_exported():
    assert impersonate.ClientPool is pool_module.ClientPool
    assert not hasattr(curl_impersonate, "ClientPool")
