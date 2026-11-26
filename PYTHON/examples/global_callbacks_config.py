from curl_impersonate import impersonate
from yarl import URL


VAR_CONFIG = {
    "BeforeRequest": {
        "changeUrl": [{
            "match": "https://www.example.com/BeforeRequest/",
            "matchMode": "equals",
            "to": "https://echo.free.beeceptor.com/BeforeRequest/",
        }],
    },
    "AfterRequest": {
        "retries": [{
            "match": "/AfterRequest/",
            "matchMode": "contains",
            "maxAttempts": 10,
            "retryUrl": "https://echo.free.beeceptor.com/AfterRequest/retries/",
            "attemptParam": "q",
        }],
    },
    "ErrorRequest": {
        "ignoreErrors": [{
            "match": "/ErrorRequest/",
            "matchMode": "endswith",
            "disableRetries": True,
        }],
    },
}


def url_matches(rule, url):
    url = str(url)
    match = rule["match"]
    match_mode = rule["matchMode"]

    if match_mode == "startswith":
        return url.startswith(match)
    if match_mode == "endswith":
        return url.endswith(match)
    if match_mode == "contains":
        return match in url
    return url == match


def find_url_rule(rules, url):
    if not rules:
        return None

    for rule in rules:
        if url_matches(rule, url):
            return rule

    return None


def before_request(ctx: impersonate.Context):
    rule = find_url_rule(
        VAR_CONFIG["BeforeRequest"]["changeUrl"],
        ctx.request.url,
    )

    if rule:
        print(f'{ctx.request.url} : Changed to {rule["to"]}')
        ctx.request.url = URL(rule["to"])


def after_request(ctx: impersonate.Context):
    # on_error handles failed requests.
    if not ctx.response or not ctx.response.success:
        return

    rule = find_url_rule(
        VAR_CONFIG["AfterRequest"]["retries"],
        ctx.request.url,
    )

    if not rule:
        return

    if ctx.retry.attempt < rule["maxAttempts"]:
        next_attempt = ctx.retry.attempt + 1

        print(
            f"{ctx.request.url} : Retrying | Attempt: "
            f'{next_attempt} / {rule["maxAttempts"]}'
        )

        if rule.get("retryUrl"):
            ctx.request.url = URL(rule["retryUrl"]).update_query(
                {rule["attemptParam"]: next_attempt}
            )

        return False

    print(
        f"{ctx.request.url} : Done! Maximum number of attempts reached."
    )


def on_error(ctx: impersonate.Context):
    rule = find_url_rule(
        VAR_CONFIG["ErrorRequest"]["ignoreErrors"],
        ctx.request.url,
    )

    if not rule:
        return

    print(f"{ctx.request.url} : Ignored error | {ctx.error}")
    ctx.request.fail_on_error = False

    if rule.get("disableRetries"):
        return True


with impersonate.Client() as client:
    client.configure(impersonate.Settings(
        impersonation_preset="chromeLast_win10",
    ))
    client.set_callbacks(impersonate.Callbacks(
        before_request=before_request,
        after_request=after_request,
        on_error=on_error,
    ))

    client.execute(
        impersonate.Get(
            url=URL("https://www.example.com/BeforeRequest/"),
        )
    )

    client.execute(
        impersonate.Get(
            url=URL("https://echo.free.beeceptor.com/AfterRequest/retries/?q=1"),
        )
    )

    client.execute(
        impersonate.Get(
            url=URL("https://127.0.0.1:1/ErrorRequest/"),
            retry=impersonate.Retry(max_attempts=100),
            check=impersonate.Check().code_contains(200),
        )
    )
