import sys
from pathlib import Path

from curl_impersonate import impersonate

preset = {
    "httpversion": "2",
    "ssl_version": "1.2",
    "ssl_version_max": "1.3",
    "ciphers": "TLS_AES_128_GCM_SHA256,TLS_AES_256_GCM_SHA384,TLS_CHACHA20_POLY1305_SHA256,ECDHE-ECDSA-AES128-GCM-SHA256,ECDHE-RSA-AES128-GCM-SHA256,ECDHE-ECDSA-AES256-GCM-SHA384,ECDHE-RSA-AES256-GCM-SHA384,ECDHE-ECDSA-CHACHA20-POLY1305,ECDHE-RSA-CHACHA20-POLY1305,ECDHE-RSA-AES128-SHA,ECDHE-RSA-AES256-SHA,AES128-GCM-SHA256,AES256-GCM-SHA384,AES128-SHA,AES256-SHA",
    "curves": "X25519MLKEM768:X25519:P-256:P-384",
    "sig_hash_algs": "mldsa44,mldsa65,mldsa87,ecdsa_secp256r1_sha256,rsa_pss_rsae_sha256,rsa_pkcs1_sha256,ecdsa_secp384r1_sha384,rsa_pss_rsae_sha384,rsa_pkcs1_sha384,rsa_pss_rsae_sha512,rsa_pkcs1_sha512",
    "ech": "attempt",
    "alpn": True,
    "alps": True,
    "tls_use_new_alps_codepoint": True,
    "cert_compression": "brotli",
    "tls_grease": True,
    "tls_renegotiation_info": True,
    "tls_status_request": True,
    "tls_session_ticket": True,
    "tls_no_session_tiket_reuse": False,
    "tls_permute_extensions": True,
    "tls_signed_cert_timestamps": True,
    "tls_extended_master_secret": True,
    "tls_key_shares_limit": 3,
    "tls_trust_anchors_hex_data": "00b808839a648c9b2d010704d679090a04d679090d04d679090c08839a648c9b2d010a04d679090604d679090f08839a648c9b2d010c0582df1302010582df13020e0582df1302130582df13020604d679090b08839a648c9b2d010d0582df13020d08839a648c9b2d010b04d679090708839a648c9b2d01120582df1302140582df13020f0582df13021204d679090804d679090504d679090104d679090408839a648c9b2d010908839a648c9b2d010808839a648c9b2d0113",
    "tls_permute_trust_anchors": False,
    "ja4_hash": "t13d1517h2_8daaf6152771_72fe7826094d",
    "http2_pseudo_headers_order": "masp",
    "http2_settings": "1:65536;2:0;4:6291456;6:262144",
    "http2_window_update": 15663105,
    "http2_no_priority": False,
    "http2_stream_weight": 256,
    "http2_stream_exclusive": 1,
    "http2_hash": "90224459f8bf70b7d0a8797eb916dbc9",
    "http_headers": [
        "Connection: keep-alive",
        "sec-ch-ua: \"Chromium\";v=\"152\", \"Not?A_Brand\";v=\"24\", \"YaBrowser\";v=\"26.10\", \"Yowser\";v=\"2.5\"",
        "sec-ch-ua-mobile: ?0",
        "sec-ch-ua-platform: \"Windows\"",
        "DNT: 1",
        "Upgrade-Insecure-Requests: 1",
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 YaBrowser/26.10.0.0 Safari/537.36",
        "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Sec-Fetch-Site: none",
        "Sec-Fetch-Mode: navigate",
        "Sec-Fetch-Dest: document",
        "Accept-Encoding: gzip, deflate, br, zstd",
        "Accept-Language: en-US,en;q=0.9"
    ],
    "sec_fetch_mode_header_order": {
        "navigate": [
            "Connection",
            "device-memory",
            "sec-ch-device-memory",
            "dpr",
            "sec-ch-dpr",
            "viewport-width",
            "sec-ch-viewport-width",
            "sec-ch-viewport-height",
            "rtt",
            "downlink",
            "ect",
            "sec-ch-ua",
            "sec-ch-ua-mobile",
            "sec-ch-ua-full-version",
            "sec-ch-ua-arch",
            "sec-ch-ua-platform",
            "sec-ch-ua-platform-version",
            "sec-ch-ua-model",
            "sec-ch-ua-bitness",
            "sec-ch-ua-wow64",
            "sec-ch-ua-full-version-list",
            "sec-ch-ua-form-factors",
            "sec-ch-prefers-color-scheme",
            "sec-ch-prefers-reduced-motion",
            "sec-ch-prefers-reduced-transparency",
            "DNT",
            "Upgrade-Insecure-Requests",
            "User-Agent",
            "Accept",
            "Sec-Fetch-Site",
            "Sec-Fetch-Mode",
            "Sec-Fetch-Dest",
            "Referer",
            "Accept-Encoding",
            "Accept-Language",
            "Cookie"
        ],
        "other": [
            "Connection",
            "Content-Length",
            "Pragma",
            "Cache-Control",
            "sec-ch-ua-full-version-list",
            "sec-ch-ua-platform",
            "viewport-width",
            "device-memory",
            "sec-ch-ua",
            "sec-ch-dpr",
            "sec-ch-ua-model",
            "#custom#",
            "sec-ch-ua-mobile",
            "sec-ch-ua-bitness",
            "sec-ch-ua-form-factors",
            "sec-ch-ua-wow64",
            "sec-ch-ua-arch",
            "sec-ch-prefers-reduced-transparency",
            "sec-ch-ua-full-version",
            "Content-Type",
            "sec-ch-viewport-width",
            "downlink",
            "sec-ch-viewport-height",
            "ect",
            "sec-ch-device-memory",
            "sec-ch-prefers-reduced-motion",
            "dpr",
            "sec-ch-prefers-color-scheme",
            "User-Agent",
            "DNT",
            "rtt",
            "sec-ch-ua-platform-version",
            "Accept",
            "Origin",
            "Sec-Fetch-Site",
            "Sec-Fetch-Mode",
            "Sec-Fetch-Dest",
            "Referer",
            "Accept-Encoding",
            "Accept-Language",
            "Cookie"
        ]
    },
    "client_hints": [
        "sec-ch-ua-full-version-list: \"Chromium\";v=\"152.0.7977.771\", \"Not?A_Brand\";v=\"24.0.0.0\", \"YaBrowser\";v=\"26.10.3.771\", \"Yowser\";v=\"2.5\"",
        "viewport-width: #random-viewport-width#",
        "device-memory: #random-memory#",
        "sec-ch-dpr: #random-dpr#",
        "sec-ch-ua-model: \"\"",
        "sec-ch-ua-bitness: \"64\"",
        "sec-ch-ua-form-factors: \"Desktop\"",
        "sec-ch-ua-wow64: ?0",
        "sec-ch-ua-arch: \"x86\"",
        "sec-ch-prefers-reduced-transparency: no-preference",
        "sec-ch-ua-full-version: \"26.10.3.771\"",
        "sec-ch-viewport-width: #random-viewport-width#",
        "downlink: #random-downlink#",
        "sec-ch-viewport-height: #random-viewport-height#",
        "ect: #random-ect#",
        "sec-ch-device-memory: #random-memory#",
        "sec-ch-prefers-reduced-motion: no-preference",
        "dpr: #random-dpr#",
        "sec-ch-prefers-color-scheme: dark",
        "rtt: #random-rtt#",
        "sec-ch-ua-platform-version: \"10.0.0\""
    ],
    "http3": {
        "ciphers": "TLS_AES_128_GCM_SHA256,TLS_AES_256_GCM_SHA384,TLS_CHACHA20_POLY1305_SHA256",
        "sig_hash_algs": "ecdsa_secp256r1_sha256,rsa_pss_rsae_sha256,rsa_pkcs1_sha256,ecdsa_secp384r1_sha384,rsa_pss_rsae_sha384,rsa_pkcs1_sha384,rsa_pss_rsae_sha512,rsa_pkcs1_sha512,rsa_pkcs1_sha1",
        "tls_grease": False,
        "tls_renegotiation_info": False,
        "tls_status_request": False,
        "tls_session_ticket": False,
        "tls_signed_cert_timestamps": False,
        "tls_extended_master_secret": False,
        "tls_key_shares_limit": 2,
        "tls_trust_anchors_hex_data": "00b804d679090c08839a648c9b2d010a04d679090508839a648c9b2d010d04d67909080582df13020d08839a648c9b2d010b04d679090408839a648c9b2d010c04d679090604d679090108839a648c9b2d010704d679090f04d67909070582df13020f08839a648c9b2d01090582df13020e08839a648c9b2d011304d679090d04d679090a08839a648c9b2d01080582df1302010582df1302140582df1302060582df13021304d679090b0582df13021208839a648c9b2d0112",
        "tls_permute_trust_anchors": True,
        "ja4_hash": "q13d0312h3_55b375c5d22e_178839b6cec1",
        "h3_hash": "f1a1843e2b6e4dfaa33a0ccd2cb4f1fa",
        "http3_frame_grease": True,
        "http3_frame_order": "SETTINGS,GREASE,PRIORITY_UPDATE,HEADERS",
        "http3_priority_update": "u=0, i",
        "http3_pseudo_headers_order": "masp",
        "http3_settings": "1:65536;6:262144;7:100;51:1;GREASE",
        "http3_permute_settings": False,
        "quic_use_0rtt": True,
        "quic_initial_packet_parameters": "packer_impl:quiche;packet_size:1250;packet_number:1;dcid_length:8;scid_length:0",
        "quic_transport_parameters": "32:65536;GREASE;5:6291456;8:100;7:6291456;9:103;6:6291456;12584:4f524947;15:AUTO;17:1@1,GREASE;12583:AUTO;1:30000;4:15728640;3:1472",
        "quic_permute_transport_parameters": True
    }
}

with impersonate.Client() as client:
    client.configure(impersonate.Settings(
        impersonation_preset="chromeLast_win10",
        error_log_level=impersonate.ErrorLogLevel.MEDIUM,
        # dns=impersonate.DnsSettings(doh_url="https://dns.google/dns-query")
    ))

    # client.set_cookies("dsfasdfsdfsdf")

    response_options = impersonate.ResponseOptions()
    response_options.include_status = True
    response_options.include_headers = True
    response_options.body_limit_kb = 100
    response_options.body_encoding = impersonate.ResponseEncoding.AUTO

    request = impersonate.Post()

    request.headers = {"test": "test2"}

    client.set_request_headers({"test1": "test"})

    request.method = "POST"
    request.connect_timeout_seconds = 5
    request.read_timeout_seconds = 5
    request.use_client_headers = True
    request.fail_on_error = True

    request.url = "https://tls.fundata.fun/tls"
    request.use_http3 = False

    # client.set_proxy("127.0.0.1", 8080)

    # client.set_proxy("127.0.0.1:8080")

    # request.body_form = [("123", "123"), ("qwe", "qwe")]

    request.body_multipart = [impersonate.MultipartField("dsfsdf", "sdfasdf")]

    print(client.execute(request).content_text)

    request.cookies = [
        impersonate.Cookie(
            name="session",
            value="abc",
            domain=".google.com"
        )
    ]

    # client.set_proxy("127.0.0.1:8080")

    client.set_cookies({"cookies": [
        {"domain": ".google.com", "expires": -1, "httpOnly": True, "name": "lang", "path": "/",
         "secure": True, "session": True, "value": "ru"}]}, rewrite=False)

    client.set_cookies([
        impersonate.Cookie(
            name="session2",
            value="abc",
            domain=".google.com"
        )
    ], rewrite=False)

    print(client.get_cookies())

    check = impersonate.Check()
    check.add("200", check.STATUS_CODE)
    check.add("ok", check.BODY, check.CONTAINS)
    check.add("captcha", check.BODY, check.NOT_CONTAINS)
    check.add(["123", "23434"], check.BODY, check.CONTAINS, match_all=True).body_contains("SSS")

    retry = impersonate.Retry(
        max_attempts=2,
        delay_ms=1000,
        log_retry_errors=False,
        error_label="test"
    )

    request.check = check
    request.retry = retry
    request.response = response_options

    # response = client.execute(request)
    # print(response.headers)
    # print(response.content)
