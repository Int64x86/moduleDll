import base64

import pytest
from yarl import URL

from curl_impersonate import impersonate
from curl_impersonate.models import _parse_proxy


def test_get_request_keeps_get_action_with_post_method():
    request = impersonate.Get(method="POST", url="https://example.org")
    native = request._native_call()
    assert native["action"] == "get"
    assert native["args"]["method"] == "POST"


def test_post_request_keeps_post_action_with_get_method():
    request = impersonate.Post(method="GET", body_raw="")
    native = request._native_call()
    assert native["action"] == "post"
    assert native["args"]["method"] == "GET"
    assert native["args"]["body"] == {
        "type": "raw",
        "data": "",
        "encoding": "utf8",
        "content_type": "",
    }


def test_http_flags_do_not_expose_http_version_type():
    request = impersonate.Get(use_http2=False, use_http3=True)
    native = request._native_call()["args"]
    assert native["use_http1"] is False
    assert native["use_http3"] is True


def test_read_timeout_serializes_to_native_response_timeout():
    request = impersonate.Get(read_timeout_seconds=25)
    native = request._native_call()["args"]
    assert native["response_timeout"] == 25


def test_request_option_names_serialize_to_native_fields():
    request = impersonate.Get(
        follow_redirects=False,
        use_client_cookies=False,
        use_client_headers=False,
        connect_timeout_seconds=7,
        response_body_file=r"C:\tmp\response.bin",
    )
    native = request._native_call()["args"]
    assert native["redirect"] is False
    assert native["use_memory_cookies"] is False
    assert native["use_memory_headers"] is False
    assert native["connection_timeout"] == 7
    assert native["out_filename"] == r"C:\tmp\response.bin"


def test_request_cookies_serialize_as_temporary_cookie_jar():
    request = impersonate.Get(cookies=[
        impersonate.Cookie(
            name="session",
            value="abc",
            domain=".example.org",
            path="/api",
            secure=True,
            http_only=True,
            expires=1_900_000_000,
            session=False,
        )
    ])

    assert request._native_call()["args"]["cookies"] == [{
        "name": "session",
        "value": "abc",
        "domain": ".example.org",
        "path": "/api",
        "secure": True,
        "httpOnly": True,
        "expires": 1_900_000_000,
        "session": False,
    }]


def test_request_uses_yarl_url_with_query_parameters():
    url = URL("https://example.org/path").with_query([
        ("tag", "one"),
        ("tag", "two"),
        ("page", "2"),
    ])
    request = impersonate.Get(url=url)
    native = request._native_call()["args"]

    assert request.url is url
    assert native["url"] == "https://example.org/path?tag=one&tag=two&page=2"
    assert "query_params" not in native


def test_request_converts_string_url_to_yarl_url():
    request = impersonate.Post(url="https://example.org/path?old=1")

    assert request.url == URL("https://example.org/path?old=1")
    assert isinstance(request.url, URL)


def test_request_converts_assigned_string_url_to_yarl_url():
    request = impersonate.Get()
    request.url = "https://example.org/changed?item=1"

    assert request.url == URL("https://example.org/changed?item=1")
    assert isinstance(request.url, URL)


def test_get_request_does_not_accept_separate_query():
    with pytest.raises(TypeError, match="unexpected keyword argument 'query'"):
        impersonate.Get(query={"page": 2})


def test_bytes_body_uses_explicit_native_base64_encoding():
    request = impersonate.Post(body_raw=b"\x00\xff")
    body = request._native_call()["args"]["body"]
    assert body == {
        "type": "raw",
        "data": base64.b64encode(b"\x00\xff").decode("ascii"),
        "encoding": "base64",
        "content_type": "",
    }


def test_json_body_keeps_json_value_for_native_serialization():
    request = impersonate.Post(body_json={"active": True, "items": [1, 2]})

    assert request._native_call()["args"]["body"] == {
        "type": "json",
        "value": {"active": True, "items": [1, 2]},
        "content_type": "",
    }


def test_form_uses_shared_params_format():
    request = impersonate.Post(body_form=[("tag", "one"), ("tag", "two")])

    assert request._native_call()["args"]["body"] == {
        "type": "urlencoded",
        "fields": [["tag", "one"], ["tag", "two"]],
        "content_type": "",
    }


def test_preencoded_form_string_is_not_changed():
    request = impersonate.Post(body_form="query=hello%20world&token=a%2Fb")

    assert request._native_call()["args"]["body"] == {
        "type": "urlencoded",
        "fields": "query=hello%20world&token=a%2Fb",
        "content_type": "",
    }


def test_multipart_serializes_typed_parts_without_magic_prefixes():
    request = impersonate.Post(body_multipart=[
        impersonate.MultipartField("description", "hello"),
        impersonate.MultipartFile(
            "document",
            r"C:\files\report.pdf",
            file_name="upload.pdf",
            content_type="application/pdf",
        ),
        impersonate.MultipartBytes(
            "payload",
            b"\x00\x01",
            file_name="payload.bin",
            content_type="application/octet-stream",
        ),
    ])

    assert request._native_call()["args"]["body"] == {
        "type": "multipart",
        "content_type": "",
        "parts": [
            {"type": "text", "name": "description", "value": "hello"},
            {
                "type": "file",
                "name": "document",
                "path": r"C:\files\report.pdf",
                "file_name": "upload.pdf",
                "content_type": "application/pdf",
            },
            {
                "type": "bytes",
                "name": "payload",
                "data": "AAE=",
                "file_name": "payload.bin",
                "content_type": "application/octet-stream",
            },
        ],
    }


def test_post_request_rejects_multiple_body_sources():
    request = impersonate.Post(
        body_raw="raw",
        body_form={"field": "value"},
    )

    with pytest.raises(ValueError, match="only one Post body source"):
        request._native_call()


def test_content_type_overrides_body_mode():
    request = impersonate.Post(
        body_json={"error": "invalid"},
        content_type="application/problem+json",
    )

    assert request._native_call()["args"]["body"]["content_type"] == (
        "application/problem+json"
    )

    multipart = impersonate.Post(
        body_multipart=[impersonate.MultipartField("name", "value")],
        content_type="multipart/mixed; boundary=custom",
    )
    assert multipart._native_call()["args"]["body"]["content_type"] == (
        "multipart/mixed; boundary=custom"
    )


def test_raw_body_rejects_implicit_json_conversion():
    request = impersonate.Post(body_raw={"use": "body_json"})

    with pytest.raises(TypeError, match="body_raw must be str, bytes, or None"):
        request._native_call()


def test_response_check_serializes_multiple_rules():
    response_check = (
        impersonate.Check()
         .add("200", impersonate.Check.STATUS_CODE)
         .add(["success", "ready"], impersonate.Check.BODY)
    )

    native = impersonate.Get(check=response_check)._native_call()["args"]
    options = native["advanced_options"]
    assert options["DetailChecking"] is True
    assert options["CheckResponseCodeData"] == {
        "rules": [
            {"type": "contains", "values": ["200"], "match_all": False}
        ]
    }
    assert options["CheckResponseBodyData"] == {
        "rules": [
            {
                "type": "contains",
                "values": ["success", "ready"],
                "match_all": False,
            }
        ]
    }


def test_check_helpers_accept_arrays_and_chain():
    check = (
        impersonate.Check()
        .code_contains([200, 201])
        .code_not_contains(500)
        .header_contains(["json", "utf-8"], match_all=True)
        .header_not_contains("text/html")
        .body_contains(["success", "ready"], match_all=True)
        .body_not_contains("captcha")
    )

    native = impersonate.Get(check=check)._native_call()["args"]
    options = native["advanced_options"]
    assert options["CheckResponseCode"] is True
    assert options["CheckResponseHeaders"] is True
    assert options["CheckResponseBody"] is True
    assert options["CheckResponseHeadersData"]["rules"][0] == {
        "type": "contains",
        "values": ["json", "utf-8"],
        "match_all": True,
    }


def test_response_options_belong_to_request():
    response = impersonate.ResponseOptions(
        include_redirect_headers=True,
        body_encoding=impersonate.ResponseEncoding.UTF_8,
        require_nonempty_body=True,
        body_limit_kb=123,
    )

    native = impersonate.Get(response=response)._native_call()["args"]
    assert native["response"] == {
        "GetStatus": True,
        "GetHeaders": True,
        "GetAllRedirectHeaders": True,
        "GetContent": True,
        "ContentEncoding": "utf-8",
        "ContentNotEmpty": True,
        "ContentAsJson": False,
        "ContentLengthLimit": 123,
    }
    assert native["advanced_options"] is None


def test_response_check_serializes_match_all_without_native_retry():
    response_check = impersonate.Check().add(
        ["a", "b"],
        impersonate.Check.HEADERS,
        match_all=True,
    )
    retry = impersonate.Retry(
        max_attempts=5,
        delay_ms=1000,
        exponential_backoff=True,
    )

    request = impersonate.Get(check=response_check, retry=retry)
    options = request._native_call()["args"]["advanced_options"]
    assert options["CheckResponseHeadersData"] == {
        "rules": [
            {"type": "contains", "values": ["a", "b"], "match_all": True}
        ]
    }
    assert "ReqRepeatOnError" not in options
    assert "MaximumFailes" not in options


def test_request_owns_response_check_and_retry_options():
    response = impersonate.ResponseOptions(body_limit_kb=321)
    response_check = impersonate.Check().add(
        "200", impersonate.Check.STATUS_CODE
    )
    retry = impersonate.Retry(max_attempts=2)

    request = impersonate.Get(
        response=response,
        check=response_check,
        retry=retry,
    )

    native = request._native_call()["args"]
    assert native["response"]["ContentLengthLimit"] == 321
    assert native["advanced_options"]["CheckResponseCode"] is True
    assert request.retry is retry


def test_retry_does_not_create_native_advanced_options():
    native = impersonate.Get(
        retry=impersonate.Retry(max_attempts=2)
    )._native_call()["args"]
    assert native["advanced_options"] is None


def test_response_check_serializes_mixed_types_for_one_target():
    response_check = (
        impersonate.Check()
         .add("ok", impersonate.Check.BODY)
         .add(
            "captcha",
            impersonate.Check.BODY,
            impersonate.Check.NOT_CONTAINS,
        )
    )

    options = impersonate.Get(
        check=response_check
    )._native_call()["args"]["advanced_options"]
    assert options["CheckResponseBodyData"] == {
        "rules": [
            {"type": "contains", "values": ["ok"], "match_all": False},
            {
                "type": "not_contains",
                "values": ["captcha"],
                "match_all": False,
            },
        ]
    }


def test_defaults_match_bas_options():
    request = impersonate.Get()._native_call()["args"]
    response = impersonate.ResponseOptions()._native()
    settings = impersonate.Settings()._native()

    assert request["method"] == "GET"
    assert request["use_http1"] is False
    assert request["use_http3"] is False
    assert request["use_proxy"] is True
    assert request["redirect"] is True
    assert request["use_memory_cookies"] is True
    assert request["use_memory_headers"] is True
    assert request["connection_timeout"] == 5
    assert request["response_timeout"] == 60
    assert response == {
        "GetStatus": True,
        "GetHeaders": True,
        "GetAllRedirectHeaders": False,
        "GetContent": True,
        "ContentEncoding": "auto",
        "ContentNotEmpty": False,
        "ContentAsJson": False,
        "ContentLengthLimit": 0,
    }
    assert impersonate.Retry().max_attempts == 1
    assert settings["errorLogLevel"] == "full"
    assert settings["LoadProxyFromProfile"] is True


def test_response_encoding_is_limited_to_native_values():
    response = impersonate.ResponseOptions(
        body_encoding=impersonate.ResponseEncoding.WINDOWS_1251
    )

    assert response._native()["ContentEncoding"] == "windows-1251"


def test_settings_serializes_structured_values():
    settings = impersonate.Settings(
        custom_preset=impersonate.CustomPreset({"httpversion": "2"}),
        certificate_signatures=impersonate.CertificateSignatures([
            "example.org:ABC",
            "api.example.org:DEF",
        ]),
        client_certificates=[
            impersonate.ClientCertificate(
                hosts=["api.example.org", "*.example.net"],
                certificate=r"C:\certs\client.pem",
                private_key=r"C:\certs\client.key",
                certificate_type=impersonate.CertificateType.PEM,
                password="secret",
            )
        ],
        dns=impersonate.DnsSettings(
            server="1.1.1.1",
            doh_url="https://cloudflare-dns.com/dns-query",
        ),
    )

    native = settings._native()
    assert native["customPreset"] == '{"httpversion":"2"}'
    assert native["certSignatures"] == "example.org:ABC;api.example.org:DEF"
    assert native["clientCertificates"] == [{
        "hosts": ["api.example.org", "*.example.net"],
        "certificate": r"C:\certs\client.pem",
        "privateKey": r"C:\certs\client.key",
        "type": "PEM",
        "password": "secret",
    }]
    assert native["PreferredDns"] == "1.1.1.1"
    assert native["DnsOverHttps"] == "https://cloudflare-dns.com/dns-query"


def test_empty_response_check_rule_is_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        impersonate.Check().add(
            [],
            impersonate.Check.BODY,
        )


def test_https_proxy_uses_https_proxy_type():
    server, port, proxy_type, username, password = _parse_proxy(
        "https://user:pass@proxy.example:8443"
    )

    assert (server, port) == ("proxy.example", 8443)
    assert proxy_type is impersonate.ProxyType.HTTPS
    assert (username, password) == ("user", "pass")


def test_cookie_generator_is_serialized():
    calls = []
    client = impersonate.Client.__new__(impersonate.Client)
    client._call = lambda action, args: calls.append((action, args))
    cookies = (
        impersonate.Cookie(name="session", value="abc", domain="example.org")
        for _ in range(1)
    )

    client.set_cookies(cookies)

    assert calls[0][1]["json_cookies"]["cookies"][0]["name"] == "session"


def test_binary_websocket_frame_is_decoded_to_bytes():
    response = impersonate.WsResponse({
        "success": True,
        "isBinary": True,
        "frame": base64.b64encode(b"\x00\xff").decode("ascii"),
    })

    assert response.frame == b"\x00\xff"


def test_null_settings_response_objects_are_empty_dicts():
    response = impersonate.SettingsResponse({
        "success": True,
        "preset": None,
        "profile": None,
    })

    assert response.preset == {}
    assert response.profile == {}
