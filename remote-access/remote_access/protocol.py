"""Wire protocol: length-prefixed, typed messages over a TLS socket."""
import json
import struct
import threading

HEADER = struct.Struct(">BI")  # 1 byte type, 4 byte big-endian length

# Message types
HELLO = 0x01
AUTH_CHALLENGE = 0x02
AUTH_RESPONSE = 0x03
AUTH_OK = 0x04
AUTH_FAIL = 0x05
FRAME = 0x10
SCREEN_INFO = 0x11
MOUSE_MOVE = 0x20
MOUSE_BUTTON = 0x21
MOUSE_SCROLL = 0x22
KEY_EVENT = 0x23

PROTOCOL_VERSION = 1
MAX_MESSAGE_SIZE = 32 * 1024 * 1024  # safety cap against a malformed/hostile peer


class ConnectionClosed(Exception):
    pass


def _recv_exact(sock, n):
    chunks = []
    remaining = n
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionClosed("peer closed connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class Connection:
    """Thread-safe framed message channel over a (TLS-wrapped) socket."""

    def __init__(self, sock):
        self.sock = sock
        self._send_lock = threading.Lock()

    def send(self, msg_type, payload=b""):
        if len(payload) > MAX_MESSAGE_SIZE:
            raise ValueError("payload too large")
        header = HEADER.pack(msg_type, len(payload))
        with self._send_lock:
            self.sock.sendall(header + payload)

    def send_json(self, msg_type, obj):
        self.send(msg_type, json.dumps(obj).encode("utf-8"))

    def recv(self):
        header = _recv_exact(self.sock, HEADER.size)
        msg_type, length = HEADER.unpack(header)
        if length > MAX_MESSAGE_SIZE:
            raise ValueError("peer sent an oversized message")
        payload = _recv_exact(self.sock, length) if length else b""
        return msg_type, payload

    def recv_json(self):
        msg_type, payload = self.recv()
        return msg_type, json.loads(payload.decode("utf-8"))

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
