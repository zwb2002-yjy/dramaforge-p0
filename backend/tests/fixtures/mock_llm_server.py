"""Synthetic HTTP fault server for the locked Proxy quality gate. No Provider IO."""

from __future__ import annotations

import json
import socket
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from typing import Any

EVENTS: list[dict[str, Any]] = []
LOCK = Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_: object) -> None:
        pass

    def respond(self, status: int, value: object) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)

    def do_GET(self) -> None:
        with LOCK:
            snapshot = list(EVENTS)
        self.respond(200, snapshot if self.path == "/events" else {"ok": True})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        with LOCK:
            EVENTS.append(
                {"model": body.get("model"), "path": self.path, "port": self.server.server_port}
            )  # type: ignore[attr-defined]
        if "/rate-limit/" in self.path:
            self.respond(429, {"error": {"message": "synthetic rate limit"}})
        elif "/unavailable/" in self.path:
            self.respond(503, {"error": {"message": "synthetic unavailable"}})
        elif "/disconnect/" in self.path:
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            self.close_connection = True
        elif "/redirect/" in self.path:
            self.send_response(307)
            self.send_header(
                "Location", "http://litellm-mock-quality:9000/redirected/v1/chat/completions"
            )
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            if "/timeout/" in self.path:
                time.sleep(3)
            self.respond(
                200,
                {
                    "id": "synthetic-completion",
                    "object": "chat.completion",
                    "created": 1,
                    "model": body.get("model"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "synthetic response"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )


if __name__ == "__main__":
    Thread(
        target=ThreadingHTTPServer(("0.0.0.0", 9001), Handler).serve_forever, daemon=True
    ).start()
    ThreadingHTTPServer(("0.0.0.0", 9000), Handler).serve_forever()
