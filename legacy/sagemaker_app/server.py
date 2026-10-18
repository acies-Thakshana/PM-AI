"""HTTP server implementing the SageMaker real-time inference contract.

SageMaker calls GET /ping and POST /invocations on port 8080.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sagemaker_app.handler import invoke, parse_payload


def _encode(payload: dict) -> bytes:
    return json.dumps(payload, default=str).encode("utf-8")


class InferenceHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        if self._path() == "/ping":
            self._send(200, {"status": "ok"})
            return
        self._send(404, {"error": "Not found. SageMaker uses /ping and /invocations."})

    def do_POST(self) -> None:  # noqa: N802
        path = self._path()
        if path == "/ping":
            self._send(200, {"status": "ok"})
            return
        if path != "/invocations":
            self._send(404, {"error": "Not found. SageMaker uses /ping and /invocations."})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        content_type = self.headers.get("Content-Type") or "application/json"
        try:
            result = invoke(parse_payload(raw, content_type))
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
            return
        except Exception as exc:
            self._send(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        self._send(200, result)

    def _path(self) -> str:
        return self.path.split("?", 1)[0].rstrip("/") or "/"

    def _send(self, status: int, payload: dict) -> None:
        body = _encode(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[sagemaker] {self.address_string()} {fmt % args}")


def main() -> None:
    host = os.environ.get("AIBI_HOST", "0.0.0.0")
    port = int(os.environ.get("AIBI_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), InferenceHandler)
    print(f"AI4BI SageMaker endpoint listening on {host}:{port}")
    server.serve_forever()
