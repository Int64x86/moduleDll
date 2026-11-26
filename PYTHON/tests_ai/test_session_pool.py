import asyncio

import pytest

import curl_impersonate
from curl_impersonate import impersonate
from curl_impersonate import pool as pool_module


class FakeClient:
    clients = []

    def __init__(self, library_path=None):
        self.closed = False
        self.calls = []
        self.clients.append(self)

    async def execute_async(self, request):
        self.calls.append(request)
        return request.url

    def close(self):
        self.closed = True


def test_flow_pool_keeps_one_client_for_the_whole_flow(monkeypatch):
    FakeClient.clients = []
    monkeypatch.setattr(pool_module, "Client", FakeClient)

    async def run():
        active = 0
        max_active = 0
        client_ids = {}

        async def flow(client, item):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            try:
                client_ids[item] = [id(client)]
                await asyncio.sleep(0.01)
                client_ids[item].append(id(client))
                await asyncio.sleep(0.01)
                client_ids[item].append(id(client))
                return item * 10
            finally:
                active -= 1

        async with impersonate.ClientSessionPool(size=2) as pool:
            results = await pool.run_all(range(5), flow)

        assert results == [0, 10, 20, 30, 40]
        assert max_active == 2
        assert all(len(set(ids)) == 1 for ids in client_ids.values())
        assert all(client.closed for client in FakeClient.clients)

    asyncio.run(run())


def test_flow_pool_releases_client_after_error(monkeypatch):
    FakeClient.clients = []
    monkeypatch.setattr(pool_module, "Client", FakeClient)

    async def run():
        async with impersonate.ClientSessionPool(size=1) as pool:
            async def fail(client, item):
                raise RuntimeError("flow failed")

            try:
                await pool.run(None, fail)
            except RuntimeError as error:
                assert str(error) == "flow failed"

            result = await pool.run(
                42,
                lambda client, item: asyncio.sleep(0, result=item),
            )
            assert result == 42

    asyncio.run(run())


def test_run_all_reports_results_as_they_finish(monkeypatch):
    FakeClient.clients = []
    monkeypatch.setattr(pool_module, "Client", FakeClient)

    async def run():
        releases = {item: asyncio.Event() for item in (1, 2)}
        completed = []

        async def flow(client, item):
            await releases[item].wait()
            return item * 10

        async with impersonate.ClientSessionPool(size=2) as pool:
            task = asyncio.create_task(pool.run_all(
                [1, 2],
                flow,
                on_result=lambda item, result: completed.append(
                    (item, result)
                ),
            ))
            while pool.active < 2:
                await asyncio.sleep(0)

            releases[2].set()
            while not completed:
                await asyncio.sleep(0)

            assert completed == [(2, 20)]
            assert pool.running
            assert not task.done()

            releases[1].set()
            assert await task == [10, 20]
            assert pool.active == 0
            assert not pool.running

        assert pool.closed

    asyncio.run(run())


def test_flow_pool_uses_request_owned_options(monkeypatch):
    FakeClient.clients = []
    monkeypatch.setattr(pool_module, "Client", FakeClient)

    async def run():
        retry = impersonate.Retry(max_attempts=2)
        callbacks = impersonate.Callbacks()
        response_options = impersonate.ResponseOptions(
            include_redirect_headers=True,
        )
        override_retry = impersonate.Retry(max_attempts=3)

        async def flow(client, item):
            await client.execute_async(
                impersonate.Get(
                    url="configured",
                    retry=retry,
                    callbacks=callbacks,
                    response=response_options,
                )
            )
            await client.execute_async(
                impersonate.Get(url="overridden", retry=override_retry)
            )

        async with impersonate.ClientSessionPool(size=1) as pool:
            client = pool.clients[0]
            await pool.run(None, flow)

            assert client.calls[0].retry is retry
            assert client.calls[0].callbacks is callbacks
            assert client.calls[0].response is response_options
            assert client.calls[1].retry is override_retry

    asyncio.run(run())


def test_flow_pool_does_not_inherit_request_pool():
    assert not issubclass(impersonate.ClientSessionPool, impersonate.ClientPool)
    assert not hasattr(impersonate.ClientSessionPool, "execute_all")


def test_run_all_cancels_and_awaits_siblings_after_error(monkeypatch):
    FakeClient.clients = []
    monkeypatch.setattr(pool_module, "Client", FakeClient)

    async def run():
        slow_started = asyncio.Event()
        slow_cancelled = asyncio.Event()

        async def flow(client, item):
            if item == "fail":
                await slow_started.wait()
                raise RuntimeError("flow failed")

            slow_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                slow_cancelled.set()
                raise

        async with impersonate.ClientSessionPool(size=2) as pool:
            try:
                await pool.run_all(["fail", "slow"], flow)
            except RuntimeError as error:
                assert str(error) == "flow failed"

            assert slow_cancelled.is_set()
            assert pool.active == 0
            assert pool.pending == 0

    asyncio.run(run())


def test_run_all_returns_exceptions_in_input_order(monkeypatch):
    FakeClient.clients = []
    monkeypatch.setattr(pool_module, "Client", FakeClient)

    async def run():
        completed = []
        failed = []

        async def flow(client, item):
            if item == "fail":
                raise RuntimeError("flow failed")
            return item.upper()

        async with impersonate.ClientSessionPool(size=3) as pool:
            results = await pool.run_all(
                ["first", "fail", "last"],
                flow,
                on_result=lambda item, result: completed.append(
                    (item, result)
                ),
                on_error=lambda item, error: failed.append((item, error)),
                return_exceptions=True,
            )

            assert pool.active == 0
            assert pool.pending == 0

        assert results[0] == "FIRST"
        assert isinstance(results[1], RuntimeError)
        assert str(results[1]) == "flow failed"
        assert results[2] == "LAST"
        assert completed == [("first", "FIRST"), ("last", "LAST")]
        assert failed[0][0] == "fail"
        assert failed[0][1] is results[1]

    asyncio.run(run())


def test_run_all_propagates_cancellation_with_return_exceptions(monkeypatch):
    FakeClient.clients = []
    monkeypatch.setattr(pool_module, "Client", FakeClient)

    async def run():
        async def flow(client, item):
            await asyncio.Event().wait()

        async with impersonate.ClientSessionPool(size=2) as pool:
            task = asyncio.create_task(pool.run_all(
                [1, 2],
                flow,
                return_exceptions=True,
            ))
            while pool.active < 2:
                await asyncio.sleep(0)

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert pool.active == 0
            assert pool.pending == 0

    asyncio.run(run())


def test_client_session_pool_is_exported():
    assert impersonate.ClientSessionPool is pool_module.ClientSessionPool
    assert not hasattr(curl_impersonate, "ClientSessionPool")
