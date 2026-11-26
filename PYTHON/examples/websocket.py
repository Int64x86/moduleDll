from curl_impersonate import impersonate

counter = 1
reconnects = 0


def handler(ctx: impersonate.WsContext, event: impersonate.WsEvent):
    global counter, reconnects

    if event.is_error:
        print("event error : " + event.error)
        if event.type == impersonate.WsEventType.CONNECT:
            event.retry()
        else:
            ctx.close()
        return

    if event.type == impersonate.WsEventType.CONNECT:
        ctx.send("hello")

    elif event.type == impersonate.WsEventType.RECV:
        print(event.text())

        if event.data == "hello":
            ctx.send("work_1")

        elif event.data == f"work_{counter}":
            if counter < 5:
                counter += 1
                ctx.send(f"work_{counter}")
            else:
                ctx.close()

    elif event.type == impersonate.WsEventType.CLOSED:
        print("finished")

        if reconnects < 1:
            reconnects += 1
            counter = 1
            ctx.reconnect()


with impersonate.Client() as client:
    client.configure(impersonate.Settings(
        impersonation_preset="chromeLast_win10",
    ))
    with client.websocket_connect(
            "wss://echo.websocket.org",
            handler,
            impersonate.WsOptions(receive_timeout_seconds=5),
    ) as ws:
        ws.monitor()
