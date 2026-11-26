from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Callable, ClassVar, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from yarl import URL

Headers = Union[str, Mapping[str, Any], Sequence[Tuple[str, Any]]]
Params = Union[str, Mapping[str, Any], Sequence[Tuple[str, Any]]]


class ProxyType(str, Enum):
    HTTP = "http"  # HTTP/1.1 proxy without TLS
    HTTPS = "https"  # HTTP/1.1 proxy secured with TLS
    HTTPS2 = "https2"  # HTTP/2 proxy secured with TLS
    HTTPS3 = "https3"  # HTTP/3 MASQUE proxy secured with QUIC and TLS
    SOCKS4 = "socks4"  # SOCKS4 proxy with local DNS resolution
    SOCKS4A = "socks4a"  # SOCKS4A proxy with DNS resolution performed by the proxy
    SOCKS5 = "socks5"  # SOCKS5 proxy with local DNS resolution
    SOCKS5A = "socks5a"  # SOCKS5 proxy with DNS resolution performed by the proxy


class ResponseEncoding(str, Enum):
    AUTO = "auto"  # Detect response encoding from headers and content.
    UTF_8 = "utf-8"  # Decode the response body as UTF-8.
    WINDOWS_1251 = "windows-1251"  # Decode the response body as Windows-1251.
    BASE64 = "base64"  # Return response bytes as Base64 text.


class WsFrameType(str, Enum):
    TEXT = 'text'  # Send or receive the frame as text.
    BASE64 = 'base64'  # Send binary data as Base64 text.


class WsEventType(str, Enum):
    CONNECT = "connect"
    SEND = "send"
    RECV = "recv"
    CLOSED = "closed"


@dataclass
class WsOptions:
    connect_timeout_seconds: int = 10
    receive_timeout_seconds: int = 5
    fail_on_error: bool = False


class AdvancedOption:
    def _native(self) -> Dict[str, Any]:
        return {}


@dataclass
class ResponseOptions(AdvancedOption):
    include_redirect_headers: bool = False  # If enabled, the variable will contain response headers from each redirect and the final response.
    body_encoding: ResponseEncoding = ResponseEncoding.AUTO  # How Response.content is decoded.
    require_nonempty_body: bool = False  # Treat an empty response body as a failed request.
    body_limit_kb: int = 0  # Stops receiving the response body when the specified size (in KB) is reached. Set to 0 to disable the limit. Helps save proxy traffic but may result in incomplete data (e.g., truncated JSON).

    def _native(self) -> Dict[str, Any]:
        return {
            "GetStatus": True,
            "GetHeaders": True,
            "GetAllRedirectHeaders": self.include_redirect_headers,
            "GetContent": True,
            "ContentEncoding": self.body_encoding.value,
            "ContentNotEmpty": self.require_nonempty_body,
            "ContentAsJson": False,
            "ContentLengthLimit": self.body_limit_kb,
        }


class CheckTarget(IntEnum):
    STATUS_CODE = 0  # Match against the HTTP status code.
    HEADERS = 1  # Match against the response headers.
    BODY = 2  # Match against the response body.


class CheckType(IntEnum):
    CONTAINS = 0  # Request succeeds only when the value is present.
    NOT_CONTAINS = 1  # Request succeeds only when the value is absent.


@dataclass
class CheckRule:
    enabled: bool = False  # Enable this rule.
    match_type: CheckType = CheckType.CONTAINS  # Required match direction.
    values: List[str] = field(default_factory=list)  # Text values to check.
    match_all: bool = False  # Require every value instead of any value.

    def native_data(self) -> str:
        if not self.values:
            return ""

        if len(self.values) == 1 and not self.match_all:
            return self.values[0]

        data = json.dumps(self.values, ensure_ascii=False, separators=(",", ":"))
        return "!" + data if self.match_all else data


@dataclass
class Check(AdvancedOption):
    STATUS_CODE: ClassVar[CheckTarget] = CheckTarget.STATUS_CODE
    HEADERS: ClassVar[CheckTarget] = CheckTarget.HEADERS
    BODY: ClassVar[CheckTarget] = CheckTarget.BODY
    CONTAINS: ClassVar[CheckType] = CheckType.CONTAINS
    NOT_CONTAINS: ClassVar[CheckType] = CheckType.NOT_CONTAINS

    detail_checking: bool = False  # Enable status, header, and body checks.
    status_code: CheckRule = field(default_factory=CheckRule)  # HTTP status-code rule.
    headers: CheckRule = field(default_factory=CheckRule)  # Response-header rule.
    body: CheckRule = field(default_factory=CheckRule)  # Response-body rule.
    _mixed_rules: Dict[CheckTarget, Dict[CheckType, CheckRule]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def add(
            self,
            value: Union[str, int, Sequence[Union[str, int]]],
            target: CheckTarget,
            mode: Optional[CheckType] = None,
            match_all: bool = False,
    ) -> "Check":
        rules = {
            self.STATUS_CODE: self.status_code,
            self.HEADERS: self.headers,
            self.BODY: self.body,
        }

        target = CheckTarget(target)
        rule = rules[target]
        mode = CheckType(mode) if mode is not None else rule.match_type

        if rule.enabled and rule.match_type != mode:
            rule = self._mixed_rules.setdefault(target, {}).setdefault(
                mode,
                CheckRule(match_type=mode),
            )

        values = [value] if isinstance(value, (str, int)) else list(value)
        values = [str(item) for item in values]
        if not values or any(not item for item in values):
            raise ValueError("Rule values must not be empty")

        rule.enabled = True
        rule.match_type = mode
        rule.values.extend(values)

        rule.match_all = match_all

        self.detail_checking = True
        return self

    def code_contains(
            self,
            value: Union[str, int, Sequence[Union[str, int]]],
            match_all: bool = False,
    ) -> "Check":
        return self.add(value, self.STATUS_CODE, self.CONTAINS, match_all)

    def code_not_contains(
            self,
            value: Union[str, int, Sequence[Union[str, int]]],
            match_all: bool = False,
    ) -> "Check":
        return self.add(value, self.STATUS_CODE, self.NOT_CONTAINS, match_all)

    def body_contains(
            self,
            value: Union[str, Sequence[str]],
            match_all: bool = False,
    ) -> "Check":
        return self.add(value, self.BODY, self.CONTAINS, match_all)

    def body_not_contains(
            self,
            value: Union[str, Sequence[str]],
            match_all: bool = False,
    ) -> "Check":
        return self.add(value, self.BODY, self.NOT_CONTAINS, match_all)

    def header_contains(
            self,
            value: Union[str, Sequence[str]],
            match_all: bool = False,
    ) -> "Check":
        return self.add(value, self.HEADERS, self.CONTAINS, match_all)

    def header_not_contains(
            self,
            value: Union[str, Sequence[str]],
            match_all: bool = False,
    ) -> "Check":
        return self.add(value, self.HEADERS, self.NOT_CONTAINS, match_all)

    def _native_check(
            self,
            target: CheckTarget,
            rule: CheckRule,
    ) -> Dict[str, Any]:
        rules = [rule, *self._mixed_rules.get(target, {}).values()]
        data = {
            "rules": [
                {
                    "type": (
                        "contains"
                        if check_rule.match_type == CheckType.CONTAINS
                        else "not_contains"
                    ),
                    "values": check_rule.values,
                    "match_all": check_rule.match_all,
                }
                for check_rule in rules
                if check_rule.enabled
            ]
        }
        return {
            "enabled": rule.enabled,
            "type": rule.match_type,
            "data": data,
        }

    def _native(self) -> Dict[str, Any]:
        status_code = self._native_check(CheckTarget.STATUS_CODE, self.status_code)
        headers = self._native_check(CheckTarget.HEADERS, self.headers)
        body = self._native_check(CheckTarget.BODY, self.body)
        return {
            "enabled": True,
            "DetailChecking": self.detail_checking,
            "CheckResponseCode": status_code["enabled"],
            "CheckResponseCodeType": status_code["type"],
            "CheckResponseCodeData": status_code["data"],
            "CheckResponseHeaders": headers["enabled"],
            "CheckResponseHeadersType": headers["type"],
            "CheckResponseHeadersData": headers["data"],
            "CheckResponseBody": body["enabled"],
            "CheckResponseBodyType": body["type"],
            "CheckResponseBodyData": body["data"],
        }


@dataclass
class Retry:
    max_attempts: int = 1  # Total attempts, including the first request.
    delay_ms: int = 0  # Pause before a retry; 0 disables the delay.
    exponential_backoff: bool = False  # Double the delay after each failed attempt.
    log_retry_errors: bool = False  # Log each failed attempt before retrying.
    rollback_cookies_on_error: bool = True  # Restore client cookies when an attempt fails.
    error_label: str = ""  # Prefix included in formatted request errors.
    attempt: int = field(default=0, init=False)  # Current attempt number.


@dataclass
class Cookie:
    name: str  # Cookie name.
    value: str  # Cookie value.
    domain: str  # Host or domain that receives the cookie.
    path: str = "/"  # URL path scope.
    secure: bool = True  # Send only over HTTPS.
    http_only: bool = True  # Mark as inaccessible to browser JavaScript.
    expires: int = -1  # Unix expiry timestamp; -1 means no explicit expiry.
    session: bool = True  # Treat the cookie as a session cookie.

    def _native(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "secure": self.secure,
            "httpOnly": self.http_only,
            "expires": self.expires,
            "session": self.session,
        }


class MultipartPart:
    def _native(self) -> Dict[str, Any]:
        raise NotImplementedError


@dataclass
class MultipartField(MultipartPart):
    name: str  # Multipart field name.
    value: Any  # Text value. JSON scalar values are converted to text by native code.

    def _native(self) -> Dict[str, Any]:
        return {
            "type": "text",
            "name": self.name,
            "value": self.value,
        }


@dataclass
class MultipartFile(MultipartPart):
    name: str  # Multipart field name.
    path: str  # Local file path read by the native module.
    file_name: str = ""  # Uploaded filename; defaults to the local filename.
    content_type: str = ""  # Part Content-Type; detected from the file when empty.

    def _native(self) -> Dict[str, Any]:
        return {
            "type": "file",
            "name": self.name,
            "path": self.path,
            "file_name": self.file_name,
            "content_type": self.content_type,
        }


@dataclass
class MultipartBytes(MultipartPart):
    name: str  # Multipart field name.
    data: bytes  # Binary part content.
    file_name: str = ""  # Uploaded filename; detected when empty.
    content_type: str = ""  # Part Content-Type; detected from the bytes when empty.

    def _native(self) -> Dict[str, Any]:
        return {
            "type": "bytes",
            "name": self.name,
            "data": base64.b64encode(self.data).decode("ascii"),
            "file_name": self.file_name,
            "content_type": self.content_type,
        }


@dataclass
class Request:
    method: str = "GET"  # HTTP method for the request.
    url: Union[str, URL] = field(default_factory=URL)  # String or yarl URL, including query parameters.
    headers: Headers = field(default_factory=dict)  # Headers for this request.
    cookies: List[Cookie] = field(default_factory=list)  # Cookies used only for this request.
    use_http2: bool = True  # Allow HTTP/2; false also disables HTTP/3 unless use_http3 is true.
    use_http3: bool = False  # Require HTTP/3 instead of HTTP/1.1 or HTTP/2.
    use_proxy: bool = True  # Use the proxy configured on Client.
    follow_redirects: bool = True  # Automatically follow HTTP redirects.
    use_client_cookies: bool = True  # Merge Client cookies with request.cookies.
    use_client_headers: bool = True  # Merge Client headers with request.headers.
    connect_timeout_seconds: int = 5  # Maximum time to establish the connection.
    read_timeout_seconds: int = 60  # Maximum wait for the first response byte.
    response_body_file: str = ""  # File path for streamed response body; an existing file is replaced.
    fail_on_error: bool = False  # Raise RequestError after the final failed attempt.
    retry: Retry = field(default_factory=Retry)  # Retry settings and current attempt state.
    check: Optional[Check] = None  # Response validation rules.
    response: ResponseOptions = field(default_factory=ResponseOptions)  # Response capture settings.
    callbacks: Optional["Callbacks"] = None  # Callbacks used only by this request.
    _action: ClassVar[str]

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "url" and isinstance(value, str):
            value = URL(value)
        super().__setattr__(name, value)

    def __post_init__(self) -> None:
        self.url = URL(self.url)

    def _native_args(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "url": str(self.url),
            "headers": _headers_to_string(self.headers),
            "cookies": [cookie._native() for cookie in self.cookies],
            "use_http1": not self.use_http2 and not self.use_http3,
            "use_http3": self.use_http3,
            "use_proxy": self.use_proxy,
            "redirect": self.follow_redirects,
            "use_memory_cookies": self.use_client_cookies,
            "use_memory_headers": self.use_client_headers,
            "connection_timeout": self.connect_timeout_seconds,
            "response_timeout": self.read_timeout_seconds,
            "out_filename": self.response_body_file,
            "response": self.response._native(),
            "advanced_options": (
                self.check._native()
                if self.check is not None else None
            ),
        }

    def _native_call(self) -> Dict[str, Any]:
        return {"action": self._action, "args": self._native_args()}


@dataclass
class Get(Request):
    _action: ClassVar[str] = "get"


@dataclass
class Post(Request):
    method: str = "POST"  # Default HTTP method; may be changed to any method with a body.
    body_raw: Optional[Union[str, bytes]] = None  # Raw UTF-8 text or binary request body.
    body_json: Any = None  # JSON body value. Mutually exclusive with other body fields.
    body_form: Optional[Params] = None  # URL-encoded fields. A string is used without re-encoding.
    body_multipart: Optional[Sequence[MultipartPart]] = None  # Multipart fields and files.
    content_type: str = ""  # Overrides the Content-Type selected for the body mode.

    _action: ClassVar[str] = "post"

    def _native_args(self) -> Dict[str, Any]:
        args = super()._native_args()
        selected = sum((
            self.body_raw is not None,
            self.body_json is not None,
            self.body_form is not None,
            self.body_multipart is not None,
        ))
        if selected > 1:
            raise ValueError(
                "Use only one Post body source: body_raw, body_json, "
                "body_form, or body_multipart"
            )

        if self.body_json is not None:
            native_body = {
                "type": "json",
                "value": self.body_json,
                "content_type": self.content_type,
            }
        elif self.body_form is not None:
            native_body = {
                "type": "urlencoded",
                "fields": _params_to_native(self.body_form),
                "content_type": self.content_type,
            }
        elif self.body_multipart is not None:
            native_body = {
                "type": "multipart",
                "parts": [part._native() for part in self.body_multipart],
                "content_type": self.content_type,
            }
        elif isinstance(self.body_raw, bytes):
            native_body = {
                "type": "raw",
                "data": base64.b64encode(self.body_raw).decode("ascii"),
                "encoding": "base64",
                "content_type": self.content_type,
            }
        else:
            if self.body_raw is not None and not isinstance(self.body_raw, str):
                raise TypeError("Post.body_raw must be str, bytes, or None")
            native_body = {
                "type": "raw",
                "data": self.body_raw or "",
                "encoding": "utf8",
                "content_type": self.content_type,
            }

        args["body"] = native_body
        return args


class ErrorLogLevel(str, Enum):
    LOW = "low"  # Log concise request errors.
    MEDIUM = "medium"  # Log standard request diagnostics.
    FULL = "full"  # Log full request diagnostics.


class CertificateType(str, Enum):
    PEM = "PEM"  # PEM certificate and separate private key.
    DER = "DER"  # DER certificate and separate private key.
    P12 = "P12"  # PKCS#12 container with certificate and private key.


@dataclass
class ClientCertificate:
    hosts: Union[str, List[
        str]] = ""  # Hosts for this certificate. Separate multiple values with commas or semicolons. Use an exact host, host:port, *.example.com for subdomains, or * for every HTTPS host. An empty value also matches every HTTPS host.
    certificate: str = ""  # Client certificate as an existing file path, inline PEM text, or Base64-encoded file bytes. If the value is not an existing file, PEM text is detected by its BEGIN header; any other value is decoded as Base64. A PEM value may contain the client certificate followed by intermediate certificates.
    private_key: str = ""  # Private key as an existing file path, inline PEM text, or Base64-encoded file bytes. If the value is not an existing file, PEM text is detected by its BEGIN header; any other value is decoded as Base64. This field is ignored for P12.
    certificate_type: CertificateType = CertificateType.PEM  # Certificate format: PEM, DER, or P12. P12 is a single PKCS#12 container with the certificate and private key.
    password: str = ""  # Password used to decrypt the private key or P12 container. Leave empty when the key is not password protected.

    def _native(self) -> Dict[str, Any]:
        return {
            "hosts": self.hosts,
            "certificate": self.certificate,
            "privateKey": self.private_key,
            "type": self.certificate_type.value,
            "password": self.password,
        }


@dataclass
class DnsSettings:
    server: str = "SYSTEM"  # DNS server used when DNS over HTTPS is disabled.
    doh_url: str = ""  # DoH has priority over Preferred DNS. Browsers use DoH by default when their preferred DNS supports it; its DNS replies can provide ECH data, so changing it can affect whether ECH is available.


@dataclass
class CertificateSignatures:
    values: List[str] = field(default_factory=list)  # Expected certificate signatures, one per host.

    def _native(self) -> str:
        return ";".join(self.values)


@dataclass
class CustomPreset:
    data: Union[str, Dict[str, Any]] = ""  # Preset JSON text or a dictionary serialized as JSON.

    def _native(self) -> str:
        if isinstance(self.data, str):
            return self.data
        return json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))


@dataclass
class Settings:
    license_key: str = ""  # License key used by the native module.
    impersonation_preset: str = ""  # TLS/HTTP browser fingerprint. Prefer chromeLast_win10 or firefoxLast_win10 for the latest version; variants: SettingsResponse.preset["storage"].
    custom_preset: Union[CustomPreset, Dict[str, Any], str] = field(
        default_factory=CustomPreset)  # Custom preset dictionary or JSON string. Built-in presets: https://cdn.fundata.fun
    include_browser_headers: bool = True  # Add and order default browser headers.
    enable_chrome_client_hints: bool = True  # Send preset client hints requested through Accept-CH.
    certificate_signatures: CertificateSignatures = field(
        default_factory=CertificateSignatures
    )
    verify_certificate_signatures: bool = False  # Fail requests whose TLS certificate signature does not match.
    client_certificates: List[ClientCertificate] = field(default_factory=list)  # Certificates selected by host.
    enable_keepalive: bool = False  # Reuse connections between requests.
    error_log_level: str = ErrorLogLevel.FULL  # Native diagnostic log detail.
    profile_path: str = ""  # Profile file storing cookies, TLS sessions, and fingerprint data.
    load_proxy_from_profile: bool = True  # Reuse the saved profile proxy when present.
    dns: DnsSettings = field(default_factory=DnsSettings)  # DNS and DNS-over-HTTPS configuration.

    def _native(self) -> Dict[str, Any]:
        custom_preset = self.custom_preset
        if isinstance(custom_preset, CustomPreset):
            custom_preset = custom_preset._native()
        elif isinstance(custom_preset, dict):
            custom_preset = json.dumps(
                custom_preset,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        return {
            "licenseKey": self.license_key,
            "impresonateBrowserName": self.impersonation_preset,
            "customPreset": custom_preset,
            "addBrowserHeaders": self.include_browser_headers,
            "useChromeHints": self.enable_chrome_client_hints,
            "certSignatures": self.certificate_signatures._native(),
            "checkSignatures": self.verify_certificate_signatures,
            "clientCertificates": [
                certificate._native()
                for certificate in self.client_certificates
            ],
            "useKeepAlive": self.enable_keepalive,
            "errorLogLevel": self.error_log_level,
            "ProfileFilePath": self.profile_path,
            "LoadProxyFromProfile": self.load_proxy_from_profile,
            "PreferredDns": self.dns.server,
            "DnsOverHttps": self.dns.doh_url,
        }


@dataclass(frozen=True)
class _NativeResponse:
    """Internal result shared by all native API actions."""

    raw: Dict[str, Any]

    @property
    def success(self) -> bool:
        return bool(self.raw.get("success"))

    @property
    def error(self) -> str:
        return str(self.raw.get("error", ""))

    @property
    def error_type(self) -> str:
        return str(self.raw.get("error_type", ""))


@dataclass(frozen=True)
class Response(_NativeResponse):
    """Result returned by Client.execute() and awaited Client.execute_async()."""

    @property
    def status(self) -> Optional[int]:
        return self.raw.get("response", {}).get("status")

    @property
    def headers(self) -> Optional[Union[str, List[str], Dict[str, Any]]]:
        return self.raw.get("response", {}).get("headers")

    @property
    def content_text(self) -> str:
        return self.raw.get("response", {}).get("content", "")

    @property
    def content_json(self) -> Any:
        content = self.content_text
        return json.loads(content) if content else None

    @property
    def url(self) -> str:
        return str(self.raw.get("url", ""))

    @property
    def proxy(self) -> str:
        return str(self.raw.get("proxy", ""))


@dataclass(frozen=True)
class WsResponse(_NativeResponse):
    """Frame returned by Client.websocket_receive()."""

    @property
    def frame(self) -> Optional[Union[str, bytes]]:
        value = self.raw.get("frame")
        if value is None:
            return None
        if self.is_binary:
            return base64.b64decode(value)
        return str(value)

    @property
    def is_binary(self) -> bool:
        return bool(self.raw.get("isBinary"))

    @property
    def frame_is_ready(self) -> bool:
        return bool(self.raw.get("FrameIsReady"))

    @property
    def proxy(self) -> str:
        return str(self.raw.get("proxy", ""))


@dataclass(frozen=True)
class SettingsResponse(_NativeResponse):
    """Result returned by Client.configure()."""

    @property
    def is_licensed(self) -> bool:
        return bool(self.raw.get("isLicensed"))

    @property
    def preset(self) -> Dict[str, Any]:
        value = self.raw.get("preset")
        return dict(value) if isinstance(value, Mapping) else {}

    @property
    def profile(self) -> Dict[str, Any]:
        value = self.raw.get("profile")
        return dict(value) if isinstance(value, Mapping) else {}

    @property
    def loaded_presets(self) -> Optional[int]:
        value = self.raw.get("loadedPresets")
        return int(value) if value is not None else None


@dataclass
class Context:
    request: Request  # Mutable request used by callbacks.
    retry: Retry  # Mutable retry state used by callbacks.
    response: Optional[Response] = None  # Result of the latest attempt.
    error: str = ""  # Error set by the native request or fail().

    def fail(self, error: str) -> None:
        self.error = error


RequestCallback = Callable[[Context], Optional[bool]]


@dataclass
class Callbacks(AdvancedOption):
    before_request: Optional[RequestCallback] = None  # Runs before every attempt.
    after_request: Optional[RequestCallback] = None  # Runs after every completed attempt.
    on_error: Optional[RequestCallback] = None  # Runs after a failed attempt, before retrying.
    use_global_callbacks: bool = True  # Also run callbacks registered on Client.


def _headers_to_string(headers: Headers) -> str:
    if isinstance(headers, str):
        return headers
    items = headers.items() if isinstance(headers, Mapping) else headers
    return "\r\n".join(f"{name}: {value}" for name, value in items)


def _params_to_native(params: Params) -> Union[str, List[List[Any]]]:
    if isinstance(params, str):
        return params
    items = params.items() if isinstance(params, Mapping) else params
    return [[str(name), value] for name, value in items]


def _parse_proxy(proxy_string: str) -> tuple[str, int, ProxyType, str, str]:
    server = ""
    port = 0
    username = ""
    password = ""
    proxy_type = None

    types = {
        "http": ProxyType.HTTP,
        "https": ProxyType.HTTPS,
        "ftp": ProxyType.HTTP,
        "socks": ProxyType.SOCKS5,
        "socks5": ProxyType.SOCKS5,
        "socks5a": ProxyType.SOCKS5A,
        "socks4": ProxyType.SOCKS4,
        "socks4a": ProxyType.SOCKS4A,
    }

    # Normalize separators
    normalized = re.sub(r"\s+", "", proxy_string)
    normalized = re.sub(r"[@\\/]", ":", normalized)

    for item in normalized.split(":"):
        el = item.lower()

        if el in types:
            proxy_type = types[el]
            continue

        if 0 < len(el) <= 5 and re.fullmatch(r"[0-9]+", el):
            port = int(el)
            continue

        if not server and ("." in item or el == "localhost"):
            server = item
            continue

        if item:
            if not username:
                username = item
            elif not password:
                password = item

    if not server or not 1 <= port <= 65535:
        raise ValueError(f"Failed to parse proxy: '{proxy_string}'")

    return server, port, proxy_type, username, password
