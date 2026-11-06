"""Synthetic upstream/second TCP client for the real Nginx authentication gate."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, status, value):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler contract
        if self.path == "/health":
            return self.respond(200, {"status": "ok"})
        if self.path == "/second-client":
            request = Request(
                "http://auth-gateway-quality:8080/api/v1/auth/login",
                data=b'{"password":"invalid"}',
                headers={"Content-Type": "application/json"},
            )
            try:
                with urlopen(request, timeout=5) as response:  # noqa: S310 - fixed test origin
                    status = response.status
            except HTTPError as error:
                status = error.code
            return self.respond(200, {"status": status})
        self.respond(404, {"code": "NOT_FOUND"})

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler contract
        data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path not in {"/api/v1/auth/login", "/api/v1/auth/register"}:
            return self.respond(404, {"code": "NOT_FOUND"})
        body = json.loads(data or "{}")
        if body.get("password") == "synthetic-valid":
            return self.respond(200, {"id": "synthetic-user"})
        self.respond(401, {"code": "UNAUTHORIZED", "detail": "invalid credentials"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
