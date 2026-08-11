"""Remote-access host (agent): runs on the machine you want to control
remotely. Captures the screen, streams it to an authenticated client, and
applies the mouse/keyboard events the client sends back."""
import argparse
import getpass
import hashlib
import hmac
import io
import os
import secrets
import socket
import ssl
import threading
import time

import mss
from PIL import Image
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Button, Controller as MouseController

from . import crypto_utils, protocol
from .protocol import Connection

MOUSE_BUTTONS = {"left": Button.left, "right": Button.right, "middle": Button.middle}

KEY_MAP = {
    "Return": Key.enter, "Escape": Key.esc, "BackSpace": Key.backspace,
    "Tab": Key.tab, "space": Key.space, "Shift_L": Key.shift, "Shift_R": Key.shift,
    "Control_L": Key.ctrl, "Control_R": Key.ctrl, "Alt_L": Key.alt, "Alt_R": Key.alt,
    "Up": Key.up, "Down": Key.down, "Left": Key.left, "Right": Key.right,
    "Delete": Key.delete, "Home": Key.home, "End": Key.end,
    "Page_Up": Key.page_up, "Page_Down": Key.page_down,
    **{f"F{i}": getattr(Key, f"f{i}") for i in range(1, 13)},
}


def resolve_key(keysym, char):
    if keysym in KEY_MAP:
        return KEY_MAP[keysym]
    if char:
        return char
    return None


class HostSession:
    def __init__(self, conn, monitor, fps, quality):
        self.conn = conn
        self.monitor = monitor
        self.fps = fps
        self.quality = quality
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self._stop = threading.Event()

    def run(self):
        capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        capture_thread.start()
        try:
            self._input_loop()
        finally:
            self._stop.set()
            capture_thread.join(timeout=2)

    def _capture_loop(self):
        interval = 1.0 / self.fps
        with mss.mss() as sct:
            while not self._stop.is_set():
                start = time.monotonic()
                try:
                    shot = sct.grab(self.monitor)
                    img = Image.frombytes("RGB", shot.size, shot.rgb)
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=self.quality)
                    self.conn.send(protocol.FRAME, buf.getvalue())
                except (protocol.ConnectionClosed, OSError):
                    self._stop.set()
                    return
                elapsed = time.monotonic() - start
                time.sleep(max(0.0, interval - elapsed))

    def _input_loop(self):
        while not self._stop.is_set():
            try:
                msg_type, obj = self.conn.recv_json()
            except (protocol.ConnectionClosed, OSError, ValueError):
                return
            self._handle_input(msg_type, obj)

    def _handle_input(self, msg_type, obj):
        w, h = self.monitor["width"], self.monitor["height"]
        ox, oy = self.monitor["left"], self.monitor["top"]
        if msg_type == protocol.MOUSE_MOVE:
            self.mouse.position = (ox + int(obj["x"] * w), oy + int(obj["y"] * h))
        elif msg_type == protocol.MOUSE_BUTTON:
            button = MOUSE_BUTTONS.get(obj.get("button"))
            if button is None:
                return
            self.mouse.position = (ox + int(obj["x"] * w), oy + int(obj["y"] * h))
            if obj.get("pressed"):
                self.mouse.press(button)
            else:
                self.mouse.release(button)
        elif msg_type == protocol.MOUSE_SCROLL:
            self.mouse.scroll(obj.get("dx", 0), obj.get("dy", 0))
        elif msg_type == protocol.KEY_EVENT:
            key = resolve_key(obj.get("keysym", ""), obj.get("char"))
            if key is None:
                return
            if obj.get("pressed"):
                self.keyboard.press(key)
            else:
                self.keyboard.release(key)


def authenticate(conn, password):
    nonce = secrets.token_hex(32)
    conn.send_json(protocol.AUTH_CHALLENGE, {"nonce": nonce})
    msg_type, obj = conn.recv_json()
    if msg_type != protocol.AUTH_RESPONSE:
        return False
    expected = hmac.new(password.encode("utf-8"), nonce.encode("utf-8"), hashlib.sha256).hexdigest()
    ok = hmac.compare_digest(expected, obj.get("hmac", ""))
    conn.send_json(protocol.AUTH_OK if ok else protocol.AUTH_FAIL, {})
    return ok


def serve_client(raw_sock, addr, ssl_ctx, password, monitor, fps, quality):
    print(f"[+] Connection from {addr}")
    try:
        tls_sock = ssl_ctx.wrap_socket(raw_sock, server_side=True)
    except ssl.SSLError as exc:
        print(f"[!] TLS handshake failed with {addr}: {exc}")
        return

    conn = Connection(tls_sock)
    try:
        msg_type, _ = conn.recv_json()
        if msg_type != protocol.HELLO:
            return
        if not authenticate(conn, password):
            print(f"[!] Authentication failed for {addr}")
            return
        print(f"[+] {addr} authenticated, streaming screen")
        conn.send_json(protocol.SCREEN_INFO, {"width": monitor["width"], "height": monitor["height"]})
        HostSession(conn, monitor, fps, quality).run()
    except (protocol.ConnectionClosed, OSError, ValueError) as exc:
        print(f"[!] Session with {addr} ended: {exc}")
    finally:
        conn.close()
        print(f"[-] Disconnected {addr}")


def main():
    parser = argparse.ArgumentParser(description="Remote-access host (runs on the machine being controlled).")
    parser.add_argument("--port", type=int, default=5900)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--monitor", type=int, default=1, help="mss monitor index (1 = primary display)")
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--quality", type=int, default=60, help="JPEG quality 1-95")
    parser.add_argument("--password", default=None, help="or set REMOTE_ACCESS_PASSWORD env var")
    args = parser.parse_args()

    password = args.password or os.environ.get("REMOTE_ACCESS_PASSWORD") or getpass.getpass("Set session password: ")
    if not password:
        raise SystemExit("A non-empty password is required.")

    ssl_ctx = crypto_utils.build_server_context()
    fingerprint = crypto_utils.fingerprint_of_pem_file(crypto_utils.CERT_PATH)
    print(f"Host certificate fingerprint (share this with the client operator to verify): {fingerprint}")

    with mss.mss() as sct:
        if args.monitor >= len(sct.monitors):
            raise SystemExit(f"Monitor index {args.monitor} does not exist (found {len(sct.monitors) - 1}).")
        monitor = sct.monitors[args.monitor]

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((args.bind, args.port))
    server_sock.listen(5)
    print(f"Listening on {args.bind}:{args.port} (monitor {args.monitor}: {monitor['width']}x{monitor['height']})")
    print("Remember to forward this port on your router if the client is on a different network.")

    try:
        while True:
            raw_sock, addr = server_sock.accept()
            threading.Thread(
                target=serve_client,
                args=(raw_sock, addr, ssl_ctx, password, monitor, args.fps, args.quality),
                daemon=True,
            ).start()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server_sock.close()


if __name__ == "__main__":
    main()
