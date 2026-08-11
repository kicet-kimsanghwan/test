"""Remote-access client (viewer/controller): connect to a host and view +
control its screen."""
import argparse
import getpass
import hashlib
import hmac
import io
import os
import queue
import socket
import ssl
import threading
import tkinter as tk

from PIL import Image, ImageTk

from . import crypto_utils, protocol
from .protocol import Connection


class Viewer:
    def __init__(self, root, conn, screen_w, screen_h):
        self.root = root
        self.conn = conn
        self.frame_queue = queue.Queue(maxsize=2)
        self.photo = None
        self.canvas_w = screen_w
        self.canvas_h = screen_h

        self.canvas = tk.Canvas(root, width=screen_w, height=screen_h, cursor="tcross")
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<ButtonPress>", lambda e: self._on_button(e, True))
        self.canvas.bind("<ButtonRelease>", lambda e: self._on_button(e, False))
        self.canvas.bind("<MouseWheel>", self._on_wheel_windows)
        self.canvas.bind("<Button-4>", lambda e: self._on_wheel_linux(1))
        self.canvas.bind("<Button-5>", lambda e: self._on_wheel_linux(-1))
        self.canvas.bind("<Configure>", self._on_resize)
        root.bind("<KeyPress>", lambda e: self._on_key(e, True))
        root.bind("<KeyRelease>", lambda e: self._on_key(e, False))

        self._poll_frames()

    def _on_resize(self, event):
        self.canvas_w = max(1, event.width)
        self.canvas_h = max(1, event.height)

    def _norm(self, event):
        x = min(max(event.x / self.canvas_w, 0.0), 1.0)
        y = min(max(event.y / self.canvas_h, 0.0), 1.0)
        return x, y

    def _on_motion(self, event):
        x, y = self._norm(event)
        self._send(protocol.MOUSE_MOVE, {"x": x, "y": y})

    def _on_button(self, event, pressed):
        button = {1: "left", 2: "middle", 3: "right"}.get(event.num)
        if not button:
            return
        x, y = self._norm(event)
        self._send(protocol.MOUSE_BUTTON, {"x": x, "y": y, "button": button, "pressed": pressed})

    def _on_wheel_windows(self, event):
        self._send(protocol.MOUSE_SCROLL, {"dx": 0, "dy": 1 if event.delta > 0 else -1})

    def _on_wheel_linux(self, direction):
        self._send(protocol.MOUSE_SCROLL, {"dx": 0, "dy": direction})

    def _on_key(self, event, pressed):
        char = event.char if event.char and event.char.isprintable() else None
        self._send(protocol.KEY_EVENT, {"keysym": event.keysym, "char": char, "pressed": pressed})

    def _send(self, msg_type, obj):
        try:
            self.conn.send_json(msg_type, obj)
        except OSError:
            pass

    def push_frame(self, jpeg_bytes):
        try:
            self.frame_queue.put_nowait(jpeg_bytes)
        except queue.Full:
            pass

    def _poll_frames(self):
        try:
            jpeg_bytes = self.frame_queue.get_nowait()
            img = Image.open(io.BytesIO(jpeg_bytes)).resize((self.canvas_w, self.canvas_h))
            self.photo = ImageTk.PhotoImage(img)
            self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        except queue.Empty:
            pass
        except Exception as exc:
            print(f"[!] Failed to render frame: {exc}")
        self.root.after(15, self._poll_frames)


def receiver_loop(conn, viewer, on_disconnect):
    try:
        while True:
            msg_type, payload = conn.recv()
            if msg_type == protocol.FRAME:
                viewer.push_frame(payload)
    except (protocol.ConnectionClosed, OSError):
        pass
    finally:
        on_disconnect()


def authenticate(conn, password):
    msg_type, obj = conn.recv_json()
    if msg_type != protocol.AUTH_CHALLENGE:
        raise RuntimeError("unexpected handshake response from host")
    nonce = obj["nonce"]
    digest = hmac.new(password.encode("utf-8"), nonce.encode("utf-8"), hashlib.sha256).hexdigest()
    conn.send_json(protocol.AUTH_RESPONSE, {"hmac": digest})
    msg_type, _ = conn.recv_json()
    return msg_type == protocol.AUTH_OK


def main():
    parser = argparse.ArgumentParser(description="Remote-access client (connect to and control a host).")
    parser.add_argument("host")
    parser.add_argument("--port", type=int, default=5900)
    parser.add_argument("--password", default=None, help="or set REMOTE_ACCESS_PASSWORD env var")
    parser.add_argument("--fingerprint", default=None, help="expected host cert fingerprint (skips TOFU auto-trust)")
    args = parser.parse_args()

    password = args.password or os.environ.get("REMOTE_ACCESS_PASSWORD") or getpass.getpass("Session password: ")

    try:
        raw_sock = socket.create_connection((args.host, args.port), timeout=10)
        ssl_ctx = crypto_utils.build_client_context()
        tls_sock = ssl_ctx.wrap_socket(raw_sock, server_hostname=args.host)
    except (OSError, ssl.SSLError) as exc:
        raise SystemExit(f"Could not connect to {args.host}:{args.port}: {exc}")

    fingerprint = crypto_utils.fingerprint_of_der(tls_sock.getpeercert(binary_form=True))
    error = crypto_utils.verify_and_pin(args.host, args.port, fingerprint, args.fingerprint)
    if error:
        tls_sock.close()
        raise SystemExit(error)

    conn = Connection(tls_sock)
    conn.send_json(protocol.HELLO, {"version": protocol.PROTOCOL_VERSION})

    if not authenticate(conn, password):
        conn.close()
        raise SystemExit("Authentication failed.")

    msg_type, info = conn.recv_json()
    if msg_type != protocol.SCREEN_INFO:
        conn.close()
        raise SystemExit("Unexpected response from host after authentication.")

    root = tk.Tk()
    root.title(f"Remote Access - {args.host}:{args.port}")
    viewer = Viewer(root, conn, info["width"], info["height"])

    def on_disconnect():
        print("[-] Disconnected from host")

    threading.Thread(target=receiver_loop, args=(conn, viewer, on_disconnect), daemon=True).start()

    try:
        root.mainloop()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
