import asyncio
import json
import re
import tempfile
from html import unescape

from yarl import URL
from curl_impersonate import impersonate

BROWSER_ENGINE = "chrome"  # chrome | firefox

if BROWSER_ENGINE == "firefox":
    # https://github.com/oss-invisible/playwright
    from invisible_playwright.async_api import InvisiblePlaywright

elif BROWSER_ENGINE == "chrome":
    # https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python
    from patchright.async_api import async_playwright

else:
    raise ValueError("Unsupported browser engine")

GOOGLE_URL = re.compile(r"^https?://([^.]+\.)*google\.com/")
GOOGLE_RESULT = re.compile(
    r'href="([^"]+)".data-ved.*?<h3[^>]*id="[\w-]+">(.*?)</h3>'
)


class BrowserSession:
    def __init__(self, launcher, context, profile_directory):
        self.launcher = launcher
        self.context = context
        self.profile_directory = profile_directory

    async def close(self):
        await self.launcher.__aexit__(None, None, None)
        self.profile_directory.cleanup()


async def start_browser():
    profile_directory = tempfile.TemporaryDirectory()
    launcher = None
    started = False

    try:
        if BROWSER_ENGINE == "firefox":
            launcher = InvisiblePlaywright(
                profile_dir=profile_directory.name,
                headless=True,
            )

            context = await launcher.__aenter__()
            started = True

        elif BROWSER_ENGINE == "chrome":
            launcher = async_playwright()
            playwright = await launcher.__aenter__()
            started = True

            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=profile_directory.name,
                channel="chrome",
                headless=True,
            )

        else:
            raise ValueError("Unsupported browser engine")

        return BrowserSession(
            launcher,
            context,
            profile_directory,
        )

    except BaseException:
        try:
            if started:
                await launcher.__aexit__(None, None, None)
        finally:
            profile_directory.cleanup()
        raise


def to_browser_cookies(cookies):
    result = []
    for cookie in cookies:
        item = {
            "name": cookie["name"],
            "value": cookie["value"],
            "domain": cookie["domain"],
            "path": cookie.get("path", "/"),
            "secure": cookie.get("secure", False),
            "httpOnly": cookie.get("httpOnly", False),
        }
        if cookie.get("expires", -1) > 0:
            item["expires"] = cookie["expires"]
        result.append(item)
    return result


def to_impersonate_cookies(cookies):
    return [
        {
            "name": cookie["name"],
            "value": cookie["value"],
            "domain": cookie["domain"],
            "path": cookie["path"],
            "secure": cookie["secure"],
            "httpOnly": cookie["httpOnly"],
            "expires": cookie["expires"],
            "session": cookie["expires"] <= 0,
        }
        for cookie in cookies
    ]


def parse_results(content):
    results = []

    for match in GOOGLE_RESULT.finditer(content):
        url = unescape(match.group(1))
        title = unescape(match.group(2))

        if url.startswith("/"):
            url = "https://www.google.com" + url

        results.append({"title": title, "url": url})

    return results


async def google_search(
        client: impersonate.Client,
        browser: BrowserSession,
        query: str
):
    context = browser.context

    async def redirect_google(route):
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=b"<!doctype html><head></head><body>PAGE BYPASSED</body></html>"
        )

    page = await context.new_page()
    await context.route(GOOGLE_URL, redirect_google)

    try:
        await page.goto("https://www.google.com/")

        # client.set_proxy("127.0.0.1:8080")

        response = await client.execute_async(
            impersonate.Get(
                url=URL("https://www.google.com/search").with_query([
                    ("ie", "UTF-8"),
                    ("q", query),
                ]),
                fail_on_error=True,
                use_http2=True,
                retry=impersonate.Retry(max_attempts=2),
            )
        )

        if "Copyright The Closure Library Authors" not in response.content_text:

            impersonate_cookies = client.get_cookies()
            if impersonate_cookies:
                await context.add_cookies(to_browser_cookies(impersonate_cookies))

            await page.evaluate(
                """content => {
                    document.open("text/html", "replace");
                    document.write(content);
                    document.close();
                }""",
                response.content_text,
            )

            match = re.search(r'sei=(.*?)"', response.content_text)
            if not match:
                raise RuntimeError("google response does not contain sei")
            sei = match[1]

            browser_cookies = await context.cookies(["https://www.google.com/"])

            # SG_SS = [c["value"] for c in browser_cookies if c["name"] == "SG_SS"][0]

            client.set_cookies(to_impersonate_cookies(browser_cookies), rewrite=True)

            response = await client.execute_async(
                impersonate.Get(
                    url=URL("https://www.google.com/search").with_query([
                        ("ie", "UTF-8"),
                        ("q", query),
                        ("sei", sei),
                    ]),
                    headers=[
                        ("Referer", client.lastUrl()),
                    ],
                    fail_on_error=True,
                    use_http2=True
                )
            )

        return parse_results(response.content_text)
    finally:
        await context.unroute(GOOGLE_URL, redirect_google)
        await page.close()


async def main():
    browser = await start_browser()

    try:
        with impersonate.Client() as client:
            client.configure(impersonate.Settings(
                impersonation_preset="firefoxLast_win10" if BROWSER_ENGINE == "firefox" else "chromeLast_win10",
                dns=impersonate.DnsSettings(doh_url="https://dns.google/dns-query")
            ))
            results = await google_search(
                client,
                browser,
                "test",
            )
            print(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
