import asyncio
import gc
import threading
import weakref

import pytest

from curl_impersonate import impersonate


class FakeRuntime:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self.dll = FakeDll()

    def call(self, handle, payload):
        self.calls.append(payload)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        if callable(result):
            return result(self.dll)
        return result


class FakeDll:
    def __init__(self):
        self.cancelled = False
        self.cancel_event = threading.Event()
        self.destroyed = []

    def ci_client_cancel(self, handle):
        self.cancelled = True
        self.cancel_event.set()

    def ci_client_destroy(self, handle):
        self.destroyed.append(handle)


def make_client(results):
    client = impersonate.Client.__new__(impersonate.Client)
    client._runtime = FakeRuntime(results)
    client._handle = object()
    client._state = threading.Condition(threading.RLock())
    client._error_lock = threading.RLock()
    client._active_calls = 0
    client._closing = False
    client._finalizer = weakref.finalize(client, lambda: None)
    client.callbacks = None
    client._async_lock = threading.RLock()
    client._async_executor = None
    client._async_worker_ident = None
    client._last_error = ""
    return client


def test_retry_repeats_failed_response_and_runs_callbacks():
    events = []
    client = make_client([
        {"success": False, "error": "first"},
        {"success": True, "response": {"status": 200}},
    ])
    callbacks = impersonate.Callbacks(
        before_request=lambda attempt: events.append(
            ("before", attempt.retry.attempt)
        ),
        after_request=lambda attempt: events.append(
            ("after", attempt.retry.attempt)
        ),
        on_error=lambda attempt: events.append(
            ("error", attempt.retry.attempt)
        ),
    )

    response = client.execute(
        impersonate.Get(
            url="https://example.org",
            retry=impersonate.Retry(
            max_attempts=2,
            rollback_cookies_on_error=False,
            ),
            callbacks=callbacks,
        ),
    )

    assert response.success is True
    assert len(client._runtime.calls) == 2
    assert events == [
        ("before", 1),
        ("after", 1),
        ("error", 1),
        ("before", 2),
        ("after", 2),
    ]


def test_global_after_false_forces_retry_without_retry_options():
    client = make_client([
        {"success": True, "response": {"status": 200}},
        {"success": True, "response": {"status": 200}},
    ])
    client.set_callbacks(impersonate.Callbacks(
        after_request=lambda attempt: False if attempt.retry.attempt == 1 else None
    ))

    response = client.execute(impersonate.Get())

    assert response.success is True
    assert len(client._runtime.calls) == 2


def test_local_after_result_skips_global_callback():
    events = []
    client = make_client([
        {"success": True},
        {"success": True},
    ])
    client.set_callbacks(impersonate.Callbacks(
        after_request=lambda attempt: events.append(("global", attempt.retry.attempt))
    ))

    def local_after(attempt):
        events.append(("local", attempt.retry.attempt))
        return False if attempt.retry.attempt == 1 else None

    client.execute(
        impersonate.Get(
            callbacks=impersonate.Callbacks(after_request=local_after),
        ),
    )

    assert events == [("local", 1), ("local", 2), ("global", 2)]


def test_local_after_true_stops_retry_and_skips_global_callback():
    events = []
    client = make_client([{"success": False, "error": "failed"}])
    client.set_callbacks(impersonate.Callbacks(
        after_request=lambda attempt: events.append("global")
    ))

    response = client.execute(
        impersonate.Get(
            callbacks=impersonate.Callbacks(
                after_request=lambda attempt: True
            ),
            retry=impersonate.Retry(
                max_attempts=2,
                rollback_cookies_on_error=False,
            ),
        ),
    )

    assert response.success is False
    assert len(client._runtime.calls) == 1
    assert events == []


def test_local_on_error_false_forces_retry_and_skips_global_callback():
    events = []
    client = make_client([
        {"success": False, "error": "first"},
        {"success": True},
    ])
    client.set_callbacks(impersonate.Callbacks(
        on_error=lambda attempt: events.append("global")
    ))

    response = client.execute(
        impersonate.Get(
            callbacks=impersonate.Callbacks(
                on_error=lambda attempt: False
            ),
        ),
    )

    assert response.success is True
    assert len(client._runtime.calls) == 2
    assert events == []


def test_fail_on_error_false_returns_last_response():
    client = make_client([{"success": False, "error": "failed"}])

    response = client.execute(
        impersonate.Get(
            fail_on_error=False,
            retry=impersonate.Retry(max_attempts=1),
        ),
    )

    assert response.success is False
    assert response.error.endswith("] failed")


def test_global_callbacks_run_after_local_callbacks():
    events = []
    client = make_client([{"success": True}])

    def local_before(attempt):
        events.append("local")
        return False

    def global_before(attempt):
        events.append("global")
        return True

    client.set_callbacks(impersonate.Callbacks(
        before_request=global_before
    ))
    callbacks = impersonate.Callbacks(
        before_request=local_before
    )

    client.execute(impersonate.Get(callbacks=callbacks))

    assert events == ["local", "global"]
    assert len(client._runtime.calls) == 1


def test_retry_log_contains_call_location(caplog):
    client = make_client([
        {"success": False, "error": "first"},
        {"success": True},
    ])

    client.execute(
        impersonate.Get(
            retry=impersonate.Retry(
                max_attempts=2,
                log_retry_errors=True,
                rollback_cookies_on_error=False,
            ),
        ),
    )

    assert "[cUrl Impersonate, test_retry.py:" in caplog.text
    assert ", 1/2] first" in caplog.text


def test_final_error_uses_bas_prefix():
    client = make_client([
        {"success": False, "error": "failed"},
        {"success": False, "error": "failed"},
    ])

    response = client.execute(
        impersonate.Get(
            fail_on_error=False,
            retry=impersonate.Retry(
                max_attempts=2,
                rollback_cookies_on_error=False,
            ),
        ),
    )

    assert response.error.startswith("[cUrl Impersonate, test_retry.py:")
    assert response.error.endswith(", 2/2] failed")


@pytest.mark.parametrize(
    ("error_type", "exception_type"),
    [
        ("LicenseError", impersonate.LicenseError),
        ("ModuleError", impersonate.ModuleError),
        ("RequestError", impersonate.RequestError),
        ("NativeError", impersonate.NativeError),
    ],
)
def test_native_error_type_selects_python_exception(error_type, exception_type):
    client = make_client([{
        "success": False,
        "error": "failed",
        "error_type": error_type,
    }])

    with pytest.raises(exception_type) as error:
        client.execute(impersonate.Get(fail_on_error=True))

    assert error.value.response.error_type == error_type


def test_zero_attempts_is_normalized_to_one():
    client = make_client([{"success": True}])

    response = client.execute(
        impersonate.Get(retry=impersonate.Retry(max_attempts=0)),
    )

    assert response.success is True
    assert len(client._runtime.calls) == 1


def test_before_callback_can_fail_without_native_request():
    client = make_client([])

    response = client.execute(
        impersonate.Get(
            fail_on_error=False,
            callbacks=impersonate.Callbacks(
                before_request=lambda context: context.fail("blocked")
            ),
        ),
    )

    assert response.success is False
    assert response.error.endswith("] blocked")
    assert client._runtime.calls == []


def test_after_callback_can_replace_response():
    client = make_client([{"success": False, "error": "native failed"}])

    def replace(context):
        context.response = impersonate.Response({
            "success": True,
            "response": {"status": 204},
        })

    response = client.execute(
        impersonate.Get(
            callbacks=impersonate.Callbacks(after_request=replace),
        ),
    )

    assert response.success is True
    assert response.status == 204


def test_before_callback_can_replace_request():
    client = make_client([{"success": True}])

    def replace(context):
        context.request = impersonate.Get(url="https://changed.example")

    client.execute(
        impersonate.Get(
            url="https://original.example",
            callbacks=impersonate.Callbacks(before_request=replace),
        ),
    )

    assert client._runtime.calls[0]["args"]["url"] == "https://changed.example"


def test_callback_exception_becomes_request_error():
    client = make_client([{"success": True}])

    def fail_callback(context):
        raise ValueError("callback failed")

    response = client.execute(
        impersonate.Get(
            fail_on_error=False,
            callbacks=impersonate.Callbacks(after_request=fail_callback),
        ),
    )

    assert response.success is False
    assert "(after_request) callback failed" in response.error


def test_unknown_error_type_uses_unknown_error():
    client = make_client([{
        "success": False,
        "error": "failed",
        "error_type": "FutureError",
    }])

    with pytest.raises(impersonate.UnknownError):
        client.execute(impersonate.Get(fail_on_error=True))


def test_low_level_error_updates_last_error():
    client = make_client([RuntimeError("native call failed")])

    with pytest.raises(RuntimeError):
        client.execute(impersonate.Get())

    assert client.wasError() is True
    assert client.lastError() == "native call failed"


def test_closed_client_has_clear_error_and_destroys_handle_once():
    client = make_client([])
    handle = client._handle

    client.close()
    client.close()

    assert client._runtime.dll.destroyed == [handle]
    with pytest.raises(RuntimeError, match="client is closed"):
        client.execute(impersonate.Get())
    assert client.lastError() == "client is closed"


def test_finalizer_destroys_unclosed_native_handle():
    native = FakeRuntime([])
    client = impersonate.Client.__new__(impersonate.Client)
    handle = object()
    reference = weakref.ref(client)
    weakref.finalize(
        client,
        impersonate.Client._finalize_handle,
        native,
        handle,
    )

    del client
    gc.collect()

    assert reference() is None
    assert native.dll.destroyed == [handle]


def test_async_execute_is_awaitable_and_keeps_call_location():
    client = make_client([{"success": False, "error": "failed"}])

    async def run():
        return await client.execute_async(
            impersonate.Get(fail_on_error=False),
        )

    response = asyncio.run(run())

    assert "test_retry.py:" in response.error
    assert "client.py:" not in response.error
    client.close()


def test_async_request_uses_submission_snapshot():
    client = make_client([{"success": True}])
    request = impersonate.Get(url="https://before.example")

    awaitable = client.execute_async(request)
    request.url = "https://after.example"
    asyncio.run(awaitable)

    assert client._runtime.calls[0]["args"]["url"] == "https://before.example"
    client.close()


def test_async_cancellation_cancels_native_request():
    def blocked(dll):
        dll.cancel_event.wait(2)
        return {"success": False, "error": "cancelled"}

    client = make_client([blocked])

    async def run():
        task = asyncio.create_task(client.execute_async(impersonate.Get()))
        while not client._runtime.calls:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert client._runtime.dll.cancelled is True
    client.close()


def test_cancelling_queued_async_request_does_not_cancel_running_request():
    release = threading.Event()

    def blocked(dll):
        release.wait(2)
        return {"success": True}

    client = make_client([blocked, {"success": True}])

    async def run():
        first = asyncio.create_task(client.execute_async(impersonate.Get()))
        while not client._runtime.calls:
            await asyncio.sleep(0)
        second = asyncio.create_task(client.execute_async(impersonate.Get()))
        await asyncio.sleep(0.01)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        assert client._runtime.dll.cancelled is False
        release.set()
        await first

    asyncio.run(run())
    client.close()
