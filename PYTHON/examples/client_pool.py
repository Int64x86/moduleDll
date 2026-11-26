import asyncio

from curl_impersonate import impersonate

use_callbacks_output = True
proxies = [
    # "http://username:password@127.0.0.1:8080",
    # "socks5://username:password@127.0.0.1:1080",
]


def print_response(request, response):
    status = response.status if response.success else response.error
    print(f"{request.url}: {status}")


async def main():
    urls = [
        "https://example.com",
        "https://tls.fundata.fun",
        "https://tls.browserleaks.com/json",
    ]
    requests = [
        impersonate.Get(
            url=url,
            retry=impersonate.Retry(max_attempts=2),
        )
        for url in urls
    ]

    async with impersonate.ClientPool(
            size=len(requests),
            settings=impersonate.Settings(impersonation_preset="chromeLast_win10"),
    ) as pool:
        for index, client in enumerate(pool.clients):
            if index < len(proxies):
                client.set_proxy(proxies[index])

        responses = []
        for i in range(3):
            responses += await pool.execute_all(
                requests,
                on_result=(
                    print_response if use_callbacks_output else None
                ),
            )

        print(
            f"running={pool.running}, "
            f"active={pool.active}, pending={pool.pending}"
        )

    if not use_callbacks_output:
        for url, response in zip(urls, responses):
            status = response.status if response.success else response.error
            print(f"{url}: {status}")


if __name__ == "__main__":
    asyncio.run(main())
