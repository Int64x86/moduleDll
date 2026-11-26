class CurlImpersonateError(RuntimeError):
    pass


class NativeLibraryError(CurlImpersonateError):
    pass


class _ResponseError(CurlImpersonateError):
    def __init__(self, response):
        self.response = response
        super().__init__(response.error or "cURL Impersonate error")


class LicenseError(_ResponseError):
    pass


class ModuleError(_ResponseError):
    pass


class RequestError(_ResponseError):
    pass


class NativeError(_ResponseError):
    pass


class UnknownError(_ResponseError):
    pass


class NetworkError(CurlImpersonateError):
    def __init__(self, message, event=None):
        self.event = event
        super().__init__(message or "Network error")


class WebSocketError(NetworkError):
    pass


class WebSocketClosed(WebSocketError):
    pass


class WebSocketTimeout(WebSocketError):
    pass


_ERROR_TYPES = {
    "LicenseError": LicenseError,
    "ModuleError": ModuleError,
    "RequestError": RequestError,
    "NativeError": NativeError,
}


def error_from_response(response):
    return _ERROR_TYPES.get(response.error_type, UnknownError)(response)
