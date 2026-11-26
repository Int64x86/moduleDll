from curl_impersonate import impersonate
import time

MAX_MESSAGES = 10
MAX_RETRIES = 3
SUBSCRIPTION = {
    "method": "SUBSCRIBE",
    "params": ["btcusdt@depth"],
    "id": 1
}


def handler(ctx: impersonate.WsContext, event: impersonate.WsEvent):
    if event.type == impersonate.WsEventType.CLOSED:
        print(f"closed: {event.close_code} {event.close_reason}")
        return

    if event.is_error:
        print(
            f"{event.type.value} error {event.curl_code}: "
            f"{event.error} (retry {event.retries}/{MAX_RETRIES})"
        )
        if event.retries < MAX_RETRIES:
            event.retry()
        else:
            ctx.close()
        return

    if event.type == impersonate.WsEventType.CONNECT:
        print("Connected")
        # ctx.send(SUBSCRIPTION)

    elif event.type == impersonate.WsEventType.RECV:
        print(event.text())
        handler.messages += 1
        time.sleep(1)
        if handler.messages >= MAX_MESSAGES:
            ctx.close()


handler.messages = 0

with impersonate.Client() as client:
    client.configure(impersonate.Settings(
        impersonation_preset="chromeLast_win10",
    ))
    with client.websocket_connect(
            "wss://stream.binance.com:443/ws/btcusdt@depth",
            handler,
            impersonate.WsOptions(receive_timeout_seconds=5),
    ) as ws:
        ws.monitor()
