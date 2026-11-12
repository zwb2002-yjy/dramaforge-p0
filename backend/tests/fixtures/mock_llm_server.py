"""Synthetic HTTP fault server for the locked Proxy quality gate. No Provider IO."""

from __future__ import annotations

import hashlib
import json
import socket
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from typing import Any

EVENTS: list[dict[str, Any]] = []
LOCK = Lock()
TOOL_NAME = "inspect_shot"
TOOL_ARGUMENTS = {
    "shot_id": "shot-fixture-1",
    "language": "中文",
    "options": {"detail": "summary"},
}


def json_hash(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def protocol_summary(body: dict[str, Any]) -> dict[str, Any]:
    """Record only protocol identifiers and hashes, never text, headers or credentials."""
    messages = []
    for message in body.get("messages", []):
        item = {"role": message.get("role")}
        if message.get("content") is not None:
            item["content_hash"] = json_hash(message["content"])
        if message.get("tool_call_id") is not None:
            item["tool_call_id"] = message["tool_call_id"]
        if message.get("tool_calls"):
            calls = []
            for call in message["tool_calls"]:
                function = call.get("function") or {}
                try:
                    arguments = json.loads(function.get("arguments", ""))
                    arguments_hash = json_hash(arguments)
                except (ValueError, TypeError):
                    arguments_hash = "invalid_json"
                calls.append({
                    "id": call.get("id"), "type": call.get("type"),
                    "name": function.get("name"), "arguments_hash": arguments_hash,
                })
            item["tool_calls"] = calls
        messages.append(item)
    choice = body.get("tool_choice")
    return {
        "messages": messages,
        "tools": [{
            "type": tool.get("type"),
            "name": (tool.get("function") or {}).get("name"),
            "parameters_hash": json_hash((tool.get("function") or {}).get("parameters")),
        } for tool in body.get("tools", [])],
        "tool_choice": choice if isinstance(choice, str) else None,
        "parallel_tool_calls": body.get("parallel_tool_calls"),
    }


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
        event = {"model": body.get("model"), "path": self.path, "port": self.server.server_port}
        if "/tools/" in self.path:
            event["protocol"] = protocol_summary(body)
        with LOCK:
            EVENTS.append(event)
        if "/tools/" in self.path:
            self.tool_completion(body)
        elif "/rate-limit/" in self.path:
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

    def tool_completion(self, body: dict[str, Any]) -> None:
        """Stateless two-turn exchange whose final answer requires the exact tool pair."""
        call_id = "call-" + str(body.get("model"))
        messages = body.get("messages", [])
        has_result = any(message.get("role") == "tool" for message in messages)
        if has_result:
            try:
                assistant, tool = messages[-2:]
                call = assistant["tool_calls"][0]
                valid = (
                    assistant["role"] == "assistant" and tool["role"] == "tool"
                    and len(assistant["tool_calls"]) == 1
                    and call["id"] == tool["tool_call_id"] == call_id
                    and call["type"] == "function"
                    and call["function"]["name"] == TOOL_NAME
                    and json.loads(call["function"]["arguments"]) == TOOL_ARGUMENTS
                    and json.loads(tool["content"]) == {
                        "ok": True, "data": {"version": 3, "title": "古桥"},
                    }
                )
            except (KeyError, ValueError, TypeError, IndexError):
                valid = False
            if not valid:
                self.respond(400, {"error": {"message": "synthetic tool pair mismatch"}})
                return
            message = {"role": "assistant", "content": "synthetic tools completed"}
            reason = "stop"
            usage = {"prompt_tokens": 19, "completion_tokens": 5, "total_tokens": 24}
        else:
            message = {
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": call_id, "type": "function",
                    "function": {
                        "name": TOOL_NAME,
                        "arguments": json.dumps(TOOL_ARGUMENTS, ensure_ascii=False),
                    },
                }],
            }
            reason = "tool_calls"
            usage = {"prompt_tokens": 13, "completion_tokens": 3, "total_tokens": 16}
        self.respond(200, {
            "id": "synthetic-tools-final" if has_result else "synthetic-tools-call",
            "object": "chat.completion", "created": 1, "model": body.get("model"),
            "choices": [{"index": 0, "message": message, "finish_reason": reason}],
            "usage": usage,
        })


if __name__ == "__main__":
    Thread(
        target=ThreadingHTTPServer(("0.0.0.0", 9001), Handler).serve_forever, daemon=True
    ).start()
    ThreadingHTTPServer(("0.0.0.0", 9000), Handler).serve_forever()
