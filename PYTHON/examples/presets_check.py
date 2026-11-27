import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from curl_impersonate import impersonate
from yarl import URL


FUNDATA_HOSTS = [
    "fundata.fun",
    "cdn.fundata.fun",
    "cdn2.fundata.fun",
]


@dataclass(frozen=True)
class FundataEndpoints:
    tls: str
    quic: str


def recv(client: impersonate.Client, host: str, path: str = "/ping", use_http3: bool = False):
    request = impersonate.Get(
        url=URL.build(scheme="https",
                      authority=host,
                      path=path,
                      ),
        use_http3=use_http3,
        fail_on_error=False,
    )

    return request, client.execute(request)


def load_endpoint_candidates(client: impersonate.Client) -> dict:
    for host in FUNDATA_HOSTS:
        _, response = recv(client, host, "/get_api_endpoints.php")
        if not response.success or response.status != 200:
            continue

        try:
            endpoints = response.content_json
        except ValueError:
            continue

        if isinstance(endpoints, dict):
            endpoints.pop("headers", None)
            return endpoints

    raise RuntimeError("fundata main endpoints unavailable")


def select_endpoint(
        client: impersonate.Client,
        candidates: list,
        use_http3: bool,
):
    for priority, host in enumerate(candidates, start=1):
        request, response = recv(client, host, use_http3=use_http3)
        if response.success and response.status == 200:
            selected_url = URL(response.url or request.url)
            return str(selected_url.origin()), priority

    return None, 0


def select_fundata_endpoints(client: impersonate.Client) -> FundataEndpoints:
    endpoints = load_endpoint_candidates(client)
    tls_candidates = list(endpoints.get("tls") or [])
    quic_candidates = list(endpoints.get("quic") or [])

    tls, tls_priority = select_endpoint(client, tls_candidates, False)
    if tls is None:
        raise RuntimeError("fundata tls endpoints unavailable")

    preferred_quic = tls_priority - 1
    if 0 < preferred_quic < len(quic_candidates):
        quic_candidates.insert(0, quic_candidates.pop(preferred_quic))

    quic, _ = select_endpoint(client, quic_candidates, True)
    if quic is None:
        raise RuntimeError("fundata quic endpoints unavailable")

    return FundataEndpoints(tls=tls, quic=quic)




class CheckType(str, Enum):
    HTTP2 = "HTTP/2"
    HTTP3 = "HTTP/3"


@dataclass
class CheckResult:
    type: CheckType
    passed: bool = False
    error: Optional[str] = None


def check_hash(
        result: CheckResult,
        name: str,
        actual: Any,
        expected: Any,
) -> bool:
    if actual == expected:
        return True

    result.error = (
        f"{name} mismatch: actual:{actual} !== expected:{expected}"
    )
    return False


def check_response(
        context: impersonate.Context,
        result: CheckResult,
        preset: dict,
        section: str,
        actual_hash_name: str,
        expected_hash_name: str,
) -> Optional[bool]:
    response = context.response

    if response is None or not response.success:
        result.passed = False
        result.error = response.error if response else context.error
        return None

    try:
        content = response.content_json or {}
    except ValueError:
        content = {}

    if not content or not content.get(section) or not content.get("tls"):
        result.passed = False
        result.error = "Bad response"
        return None

    actual_ja4 = content["tls"].get("ja4_hash")
    expected_ja4 = preset.get("ja4_hash")

    if isinstance(expected_ja4, dict):
        reused = result.passed
        stage = "reused" if reused else "initial"

        result.passed = check_hash(
            result,
            f"{stage} ja4_hash",
            actual_ja4,
            expected_ja4.get(stage),
        )

        if not reused and result.passed:
            return False
    else:
        result.passed = check_hash(
            result,
            "ja4_hash",
            actual_ja4,
            expected_ja4,
        )

    result.passed = result.passed and check_hash(
        result,
        f"{section}_hash",
        content[section].get(actual_hash_name),
        preset.get(expected_hash_name),
    )
    return None


async def check_protocol(
        client: impersonate.Client,
        raw_preset: dict,
        endpoint: str,
        check_type: CheckType,
) -> Optional[CheckResult]:
    if check_type == CheckType.HTTP3:
        preset = raw_preset.get("http3")
        if not preset:
            return None
        section = "http3"
        actual_hash_name = "h3_hash"
        expected_hash_name = "h3_hash"
    else:
        preset = raw_preset
        section = "http2"
        actual_hash_name = "h2_hash"
        expected_hash_name = "http2_hash"

    result = CheckResult(type=check_type)
    request = impersonate.Get(
        url=endpoint,
        use_http3=check_type == CheckType.HTTP3,
        fail_on_error=False,
        retry=impersonate.Retry(max_attempts=2),
        callbacks=impersonate.Callbacks(
            after_request=lambda context: check_response(
                context,
                result,
                preset,
                section,
                actual_hash_name,
                expected_hash_name,
            ),
        ),
    )
    await client.execute_async(request)
    return result


async def check_preset(
        client: impersonate.Client,
        name: str,
        endpoints: FundataEndpoints,
):
    settings = client.configure(impersonate.Settings(
        impersonation_preset=name,
    ))
    preset = settings.preset.get("raw") or {}

    return [
        await check_protocol(
            client,
            preset,
            endpoints.tls,
            CheckType.HTTP2,
        ),
        await check_protocol(
            client,
            preset,
            endpoints.quic,
            CheckType.HTTP3,
        ),
    ]


def format_result(result: CheckResult):
    if result.passed:
        return f"{result.type.value} ok"
    error = f" ({result.error})" if result.error else ""
    return f"{result.type.value} fail{error}"


def print_preset(name: str, results):
    text = ", ".join(
        format_result(result)
        for result in results
        if result is not None
    )
    print(f"{name}: {text}")


def load_runtime_data():
    with impersonate.Client() as client:
        settings = client.configure(impersonate.Settings())
        endpoints = select_fundata_endpoints(client)
        names = settings.preset.get("storage", [])
        return names, endpoints


async def check_all():
    names, endpoints = await asyncio.to_thread(load_runtime_data)

    async def run_check(client, name):
        return await check_preset(client, name, endpoints)

    async with impersonate.ClientSessionPool(size=len(names)) as pool:
        await pool.run_all(
            names,
            run_check,
            on_result=print_preset,
        )


if __name__ == "__main__":
    asyncio.run(check_all())
