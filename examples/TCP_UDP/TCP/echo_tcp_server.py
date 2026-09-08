import argparse
import asyncio
import ssl
import socket


def hex_dump(data: bytes) -> str:
    return " ".join(f"{b:02x}" for b in data)


def utf8_dump(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    ssl_object = writer.get_extra_info("ssl_object")

    print(f"\nTLS TCP client connected: {peer}")

    if ssl_object:
        print(f"TLS version : {ssl_object.version()}")
        print(f"Cipher      : {ssl_object.cipher()}")

    sock = writer.get_extra_info("socket")

    if sock is not None:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception as e:
            print(f"SO_KEEPALIVE set failed: {e}")

    try:
        while True:
            data = await reader.read(64 * 1024)

            if not data:
                print(f"client disconnected: {peer}")
                break

            print(f"\n=== TCP TLS DATA {len(data)} bytes ===")
            print(f"PEER : {peer}")
            print(f"HEX  : {hex_dump(data)}")
            print(f"UTF8 : {utf8_dump(data)}")

            if data.strip() == b"PING":
                print("PING received, ignored")
                continue

            writer.write(data)
            await writer.drain()

            print(f"echo sent {len(data)} bytes")

    except asyncio.CancelledError:
        raise

    except Exception as e:
        print(f"client error {peer}: {e}")

    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

        print(f"connection closed: {peer}")


async def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=12806)
    parser.add_argument("--cert", default="../server.crt")
    parser.add_argument("--key", default="../server.key")

    args = parser.parse_args()

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(certfile=args.cert, keyfile=args.key)

    ssl_context.minimum_version = ssl.TLSVersion.TLSv1_3

    server = await asyncio.start_server(
        handle_client,
        host=args.host,
        port=args.port,
        ssl=ssl_context,
    )

    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
    print(f"SSL TCP echo server listening on {addrs}")

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())