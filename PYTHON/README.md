# cURL Impersonate — Python SDK

[English](#english) | [Русский](#russian)

<a id="english"></a>

## English

Native browser impersonation for Python: browser TLS/HTTP fingerprints, HTTP/2
and HTTP/3, proxies, cookies, retries, WebSocket, and asynchronous execution.

> Windows x64 · Python 3.9+

## Highlights

- Lightweight Python API centered on `Client`, `Get`, `Post`, and `Settings`; `yarl` is the only Python dependency.
- GET, POST, custom HTTP methods, redirects, query parameters, and four body modes.
- Client cookies, headers, proxies, profiles, DNS-over-HTTPS, and client certificates.
- Response checks, retries, callbacks, `asyncio`, and reusable client pools.
- Text and binary WebSocket frames through the same native impersonate.

## Install

Run this command from the distributed `PYTHON` directory:

```powershell
python -m pip install .
```

`python -m pip` ensures that the package is installed for the selected Python
interpreter. For direct source execution, keep the `curl_impersonate` directory
intact. `curl_impersonate/bin` contains the loader and its required native
libraries.

## Quick start

```python
from curl_impersonate import impersonate
from yarl import URL


impersonate.set_module_version("4.5.8")

with impersonate.Client() as client:
    settings = client.configure(impersonate.Settings(
        license_key="YOUR-LICENSE-KEY",
        impersonation_preset="chromeLast_win10",
    ))

    response = client.execute(impersonate.Get(
        url=URL("https://example.org").with_query([
            ("tag", "python"),
            ("tag", "curl"),
        ]),
        headers=[("Accept", "application/json")],
        use_http2=True,
        connect_timeout_seconds=5,
        read_timeout_seconds=30,
    ))

    print(response.status)
    print(response.content_text)
```

`set_module_version(version)` specifies the native module version to use, automatically downloading it if necessary.

Use a `*Last_win10` preset to follow the latest bundled browser version. All
available variants are returned in `settings.preset["storage"]`.

## Request bodies

`Get` uses the native no-body path. `Post` uses the body path and adds
`Content-Length`, even for an empty body. Either request may use a custom HTTP
method through `request.method`.

Choose exactly one `Post` body field:

| Field | Use it for | Example |
| --- | --- | --- |
| `body_json` | JSON values | `{"active": True}` |
| `body_form` | URL-encoded fields | `[("tag", "one"), ("tag", "two")]` |
| `body_raw` | Text or bytes | `b"raw bytes"` |
| `body_multipart` | Fields and files | `MultipartField`, `MultipartFile` |

```python
request = impersonate.Post(
    url=URL("https://example.org/api"),
    body_json={"active": True},
)

upload = impersonate.Post(
    url=URL("https://example.org/upload"),
    body_multipart=[
        impersonate.MultipartField("description", "report"),
        impersonate.MultipartFile("document", r"C:\files\report.pdf"),
    ],
)
```

The native module selects `Content-Type` from the chosen body mode. A non-empty
`content_type` overrides it. Leave it empty for generated multipart bodies so
the native header contains the matching boundary.

`url` accepts either `str` or `yarl.URL`; `request.url` is normalized to a
`yarl.URL` object. Build query parameters with `URL.with_query()` and change
them later with `URL.update_query()`; both methods return a new URL object.

## Response checks and retries

```python
response_options = impersonate.ResponseOptions(
    body_encoding=impersonate.ResponseEncoding.AUTO,
    body_limit_kb=128,
)

request = impersonate.Get(
    url="https://example.org",
    response=response_options,
    check=(
        impersonate.Check()
        .code_contains([200, 204])
        .header_contains("application/json")
        .body_not_contains(["captcha", "blocked"], match_all=False)
    ),
    retry=impersonate.Retry(
        max_attempts=3,
        delay_ms=1000,
        exponential_backoff=True,
        log_retry_errors=True,
    ),
)

response = client.execute(request)
```

`Check.add(value, target, mode, match_all=False)` supports scalar values and
lists. Convenience methods are `code_contains`, `code_not_contains`,
`header_contains`, `header_not_contains`, `body_contains`, and
`body_not_contains`.

## Asyncio

```python
import asyncio

from curl_impersonate import impersonate


async def main():
    with impersonate.Client() as client:
        response = await client.execute_async(
            impersonate.Get(url="https://example.org")
        )
        print(response.status)


asyncio.run(main())
```

One `Client` owns one native worker and executes its asynchronous requests in
submission order. Use `ClientPool` for parallel independent requests or
`ClientSessionPool` when each task needs persistent cookies and profile state.

## Errors

By default, request failures are returned as `Response`:

```python
response = client.execute(request)
if not response.success:
    print(response.error_type, response.error)
```

Set `request.fail_on_error = True` to raise `LicenseError`, `ModuleError`,
`RequestError`, `NativeError`, or `UnknownError`. Native loading failures raise
`NativeLibraryError`.

The latest client state is also available through `client.wasError()`,
`client.lastError()`, and `client.lastUrl()`.

## Examples

| Topic | Files |
| --- | --- |
| HTTP and sessions | [`http_test.py`](examples/http_test.py), [`google_search.py`](examples/google_search.py) |
| Parallel clients | [`client_pool.py`](examples/client_pool.py), [`client_session_pool.py`](examples/client_session_pool.py) |
| Retry callbacks | [`global_callbacks_config.py`](examples/global_callbacks_config.py) |
| WebSocket | [`websocket.py`](examples/websocket.py), [`websocket_binance.py`](examples/websocket_binance.py) |
| Preset validation | [`presets_check.py`](examples/presets_check.py) |

---

<a id="russian"></a>

## Русский

Python SDK для запросов с TLS/HTTP fingerprint браузеров. Поддерживает HTTP/2,
HTTP/3, прокси, cookies, retry, WebSocket и asyncio.

> Windows x64 · Python 3.9+

## Возможности

- Лёгкий Python API с понятными классами `Client`, `Get`, `Post` и `Settings`; единственная Python-зависимость — `yarl`.
- GET, POST, произвольные HTTP-методы, редиректы, query-параметры и четыре формата тела запроса.
- Cookies, заголовки, прокси, профили, DNS-over-HTTPS и клиентские сертификаты.
- Проверка ответов, retry, callbacks, asyncio и пулы клиентов.
- Текстовые и бинарные WebSocket-фреймы.

## Установка

Запустите из директории `PYTHON`:

```powershell
python -m pip install .
```

`python -m pip` устанавливает пакет для выбранного интерпретатора Python. При
запуске без установки не перемещайте файлы внутри `curl_impersonate`: loader и
необходимые DLL находятся в `curl_impersonate/bin`.

## Быстрый старт

```python
from curl_impersonate import impersonate
from yarl import URL


impersonate.set_module_version("4.5.8")

with impersonate.Client() as client:
    settings = client.configure(impersonate.Settings(
        license_key="YOUR-LICENSE-KEY",
        impersonation_preset="chromeLast_win10",
    ))

    response = client.execute(impersonate.Get(
        url=URL("https://example.org").with_query([
            ("tag", "python"),
            ("tag", "curl"),
        ]),
        headers=[("Accept", "application/json")],
        use_http2=True,
        connect_timeout_seconds=5,
        read_timeout_seconds=30,
    ))

    print(response.status)
    print(response.content_text)
```

`set_module_version(version) задаёт версию нативного модуля, автоматически загружая её при необходимости.

Пресет `*Last_win10` выбирает последнюю встроенную версию браузера. Список всех
пресетов находится в `settings.preset["storage"]`.

## Тело запроса

`Get` отправляет запрос без тела и не добавляет `Content-Length`. `Post`
добавляет `Content-Length`, даже если тело пустое. HTTP-метод можно изменить
через `request.method` в обоих классах.

В `Post` используйте только один формат тела:

| Поле | Данные | Пример |
| --- | --- | --- |
| `body_json` | JSON | `{"active": True}` |
| `body_form` | URL-encoded поля | `[("tag", "one"), ("tag", "two")]` |
| `body_raw` | Текст или bytes | `b"raw bytes"` |
| `body_multipart` | Multipart-поля и файлы | `MultipartField`, `MultipartFile` |

```python
request = impersonate.Post(
    url=URL("https://example.org/api"),
    body_json={"active": True},
)

upload = impersonate.Post(
    url=URL("https://example.org/upload"),
    body_multipart=[
        impersonate.MultipartField("description", "report"),
        impersonate.MultipartFile("document", r"C:\files\report.pdf"),
    ],
)
```

Модуль сам выбирает `Content-Type` по заполненному полю тела. Непустой
`content_type` всегда имеет приоритет. Для multipart не задавайте его без
необходимости: модуль добавит правильный boundary.

`url` принимает `str` или `yarl.URL`; в `request.url` всегда хранится
`yarl.URL`. Добавляйте query-параметры через `URL.with_query()`, а изменяйте
через `URL.update_query()`. Оба метода возвращают новый URL.

## Проверка ответов и retry

```python
response_options = impersonate.ResponseOptions(
    body_encoding=impersonate.ResponseEncoding.AUTO,
    body_limit_kb=128,
)

request = impersonate.Get(
    url="https://example.org",
    response=response_options,
    check=(
        impersonate.Check()
        .code_contains([200, 204])
        .header_contains("application/json")
        .body_not_contains(["captcha", "blocked"], match_all=False)
    ),
    retry=impersonate.Retry(
        max_attempts=3,
        delay_ms=1000,
        exponential_backoff=True,
        log_retry_errors=True,
    ),
)

response = client.execute(request)
```

`Check.add(value, target, mode, match_all=False)` работает с одним значением и
со списком. Также доступны `code_contains`, `code_not_contains`,
`header_contains`, `header_not_contains`, `body_contains` и
`body_not_contains`.

## Asyncio

```python
import asyncio

from curl_impersonate import impersonate


async def main():
    with impersonate.Client() as client:
        response = await client.execute_async(
            impersonate.Get(url="https://example.org")
        )
        print(response.status)


asyncio.run(main())
```

Вызовы `execute_async()` одного `Client` выполняются последовательно. Для
параллельных независимых запросов используйте `ClientPool`. Если каждой задаче
нужны свои cookies и состояние профиля, используйте `ClientSessionPool`.

## Ошибки

По умолчанию ошибка запроса возвращается в `Response`:

```python
response = client.execute(request)
if not response.success:
    print(response.error_type, response.error)
```

Установите `request.fail_on_error = True`, чтобы выбрасывать исключения
`LicenseError`, `ModuleError`, `RequestError`, `NativeError` или `UnknownError`.
При ошибке загрузки DLL выбрасывается `NativeLibraryError`.

Результат последней операции также доступен через `client.wasError()`,
`client.lastError()` и `client.lastUrl()`.

## Примеры

| Тема | Файлы |
| --- | --- |
| HTTP и сессии | [`http_test.py`](examples/http_test.py), [`google_search.py`](examples/google_search.py) |
| Параллельные запросы | [`client_pool.py`](examples/client_pool.py), [`client_session_pool.py`](examples/client_session_pool.py) |
| Retry callbacks | [`global_callbacks_config.py`](examples/global_callbacks_config.py) |
| WebSocket | [`websocket.py`](examples/websocket.py), [`websocket_binance.py`](examples/websocket_binance.py) |
| Проверка пресетов | [`presets_check.py`](examples/presets_check.py) |
