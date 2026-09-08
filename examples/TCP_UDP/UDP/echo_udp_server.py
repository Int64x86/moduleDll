import argparse
import asyncio

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import (
    ProtocolNegotiated,
    StreamDataReceived,
    ConnectionTerminated,
    DatagramFrameReceived,
)


def hex_dump(data: bytes) -> str:
    return " ".join(f"{b:02x}" for b in data)


def utf8_dump(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def stream_type(stream_id: int) -> str:
    mod = stream_id % 4

    if mod == 0:
        return "client bidi"

    if mod == 1:
        return "server bidi"

    if mod == 2:
        return "client uni"

    return "server uni"


def is_unidirectional_stream(stream_id: int) -> bool:
    return (stream_id & 0x02) != 0


class RawEchoQuicProtocol(QuicConnectionProtocol):
    def quic_event_received(self, event):
        if isinstance(event, ProtocolNegotiated):
            print(f"ALPN: {event.alpn_protocol}")
            return

        if isinstance(event, StreamDataReceived):
            self.handle_stream_data(event)
            return

        if isinstance(event, ConnectionTerminated):
            print(
                "connection terminated: "
                f"error_code={event.error_code}, "
                f"frame_type={event.frame_type}, "
                f"reason={event.reason_phrase}"
            )
            return

    def handle_stream_data(self, event: StreamDataReceived):
        stream_id = event.stream_id
        data = event.data

        # Ignore HTTP/3 control stream, QPACK encoder/decoder, etc.
        if stream_id % 4 == 2:
            return

        if is_unidirectional_stream(stream_id):
            return

        print(f"\n=== BI STREAM DATA {len(data)} bytes ===")
        print(f"STREAM ID: {stream_id}")
        print(f"TYPE     : {stream_type(stream_id)}")
        print(f"HEX      : {hex_dump(data)}")
        print(f"UTF8     : {utf8_dump(data)}")

        # keep-alive
        if data.strip() == b"PING":
            print("PING received, ignored")
            return

        try:
            self._quic.send_stream_data(
                stream_id=stream_id,
                data=data,
                end_stream=False,
            )
            self.transmit()
            print(f"echo sent {len(data)} bytes")

        except Exception as e:
            print(f"echo failed on stream {stream_id}: {e}")

        if event.end_stream:
            print(f"stream {stream_id} ended by peer")


async def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=12806)
    parser.add_argument("--cert", default="../server.crt")
    parser.add_argument("--key", default="../server.key")

    args = parser.parse_args()

    config = QuicConfiguration(
        is_client=False,
        alpn_protocols=["h3"],
    )

    config.load_cert_chain(args.cert, args.key)

    print(f"Python QUIC echo server listening on {args.host}:{args.port} UDP")

    await serve(
        host=args.host,
        port=args.port,
        configuration=config,
        create_protocol=RawEchoQuicProtocol,
    )

    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())