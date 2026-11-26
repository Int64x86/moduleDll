import asyncio
from urllib.parse import quote_plus

from curl_impersonate import impersonate


async def account_flow(client: impersonate.Client, account):
    login = account["login"]

    client.reset()

    response = await client.execute_async(
        impersonate.Get(
            url="https://httpbin.org/anything/login?token=demo-token",
            fail_on_error=True,
            retry=impersonate.Retry(max_attempts=2, delay_ms=500),
        ),
    )

    data = response.content_json or {}
    token = data.get("args", {}).get("token", "")
    if not token:
        raise RuntimeError("login token was not found")

    login_response = await client.execute_async(
        impersonate.Post(
            url="https://httpbin.org/anything/login",
            body_json={
                "login": login,
                "password": account["password"],
                "token": token,
            },
            retry=impersonate.Retry(max_attempts=2, delay_ms=500),
        ),
    )
    if not login_response.success:
        return {
            "login": login,
            "success": False,
            "error": login_response.error,
        }

    profile = await client.execute_async(
        impersonate.Get(
            url=(
                    "https://httpbin.org/anything/profile?login="
                    + quote_plus(login)
            ),
            retry=impersonate.Retry(max_attempts=2, delay_ms=500),
        ),
    )
    if not profile.success:
        return {
            "login": login,
            "success": False,
            "error": profile.error,
        }

    return {
        "login": login,
        "success": True,
        "profile": profile.content_json,
    }


def print_result(account, result):
    status = "ok" if result["success"] else result["error"]
    print(f'{account["login"]}: {status}')


async def main():
    accounts = [
        {"login": "user_1", "password": "password_1"},
        {"login": "user_2", "password": "password_2"},
        {"login": "user_3", "password": "password_3"},
        {"login": "user_4", "password": "password_4"},
        {"login": "user_5", "password": "password_5"},
    ]

    async with impersonate.ClientSessionPool(
            size=4,
            settings=impersonate.Settings(
                impersonation_preset="chromeLast_win10",
            ),
    ) as pool:
        results = await pool.run_all(
            accounts,
            account_flow,
            on_result=print_result,
        )
        print(
            f"running={pool.running}, "
            f"active={pool.active}, pending={pool.pending}"
        )

    print(f"completed={len(results)}, closed={pool.closed}")


if __name__ == "__main__":
    asyncio.run(main())
