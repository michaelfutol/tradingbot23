"""Private loopback bridge. Commands are queued for the existing GUI owner."""

import copy
import json
import os
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class LocalBridge:
    ACTIONS = {"pause", "resume", "run-once"}

    def __init__(self, data_dir: Path, port: int):
        self.access_file = data_dir / "bridge_access.json"
        self.token = secrets.token_urlsafe(32)
        self.commands = queue.Queue(maxsize=16)
        self._lock = threading.Lock()
        self._snapshot = {"ready": False}
        self._operations = {}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def setup(self):
                super().setup()
                self.connection.settimeout(3)

            def reply(self, code, payload):
                body = json.dumps(payload, allow_nan=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True

            def authorized(self):
                if self.headers.get("Origin") or self.headers.get("Host") != owner.host:
                    self.reply(403, {"error": "Local command clients only"})
                    return False
                supplied = self.headers.get("Authorization", "")
                if not secrets.compare_digest(supplied.encode(), ("Bearer " + owner.token).encode()):
                    self.reply(401, {"error": "Authentication required"})
                    return False
                return True

            def do_GET(self):
                if not self.authorized():
                    return
                with owner._lock:
                    if self.path == "/status":
                        payload = copy.deepcopy(owner._snapshot)
                    elif self.path in {"/history", "/p2p"}:
                        payload = copy.deepcopy(owner._snapshot.get(self.path[1:], {}))
                    elif self.path.startswith("/operations/"):
                        payload = copy.deepcopy(owner._operations.get(self.path.rsplit("/", 1)[-1]))
                    else:
                        payload = None
                self.reply(200 if payload is not None else 404, payload or {"error": "Not found"})

            def do_POST(self):
                if not self.authorized():
                    return
                if self.path != "/commands":
                    self.reply(404, {"error": "Not found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 1024 or self.headers.get("Transfer-Encoding"):
                        raise ValueError()
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict) or set(payload) != {"action"}:
                        raise ValueError()
                    action = payload["action"]
                    if action not in owner.ACTIONS:
                        raise ValueError()
                    operation = owner.submit(action)
                except (ValueError, TypeError, queue.Full):
                    self.reply(400, {"error": "Invalid action or full command queue"})
                    return
                self.reply(202, operation)

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.host = f"127.0.0.1:{self.server.server_port}"
        self.url = "http://" + self.host
        self.access_file.write_text(json.dumps({"url": self.url, "token": self.token,
                                                "pid": os.getpid()}), encoding="utf-8")
        self.access_file.chmod(0o600)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def submit(self, action):
        with self._lock:
            operation = {"id": secrets.token_hex(12), "action": action, "state": "queued"}
            self.commands.put_nowait(operation)
            self._operations[operation["id"]] = operation
            while len(self._operations) > 100:
                oldest = next(iter(self._operations))
                if self._operations[oldest]["state"] in {"queued", "running"}:
                    break
                del self._operations[oldest]
            return copy.deepcopy(operation)

    def complete(self, operation_id, state="completed", **result):
        with self._lock:
            self._operations[operation_id].update(state=state, **result)

    def publish(self, snapshot):
        with self._lock:
            self._snapshot = copy.deepcopy(snapshot)
            self._snapshot["snapshot_at_unix"] = time.time()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        if self.access_file.exists():
            saved = json.loads(self.access_file.read_text(encoding="utf-8"))
            if saved.get("token") == self.token:
                self.access_file.unlink()
