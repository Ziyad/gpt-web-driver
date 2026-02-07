from __future__ import annotations

from dataclasses import dataclass
import http.server
import socketserver
import threading
from pathlib import Path
from typing import Optional


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


@dataclass(frozen=True)
class DemoServer:
    base_url: str
    _server: socketserver.TCPServer
    _thread: threading.Thread

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


def serve_directory(directory: Path, *, host: str = "127.0.0.1", port: int = 0) -> DemoServer:
    directory = directory.resolve()

    def handler(*args, **kwargs):
        return _QuietHandler(*args, directory=str(directory), **kwargs)

    class _TCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    httpd = _TCPServer((host, port), handler)
    t = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    t.start()

    actual_port = httpd.server_address[1]
    return DemoServer(base_url=f"http://{host}:{actual_port}", _server=httpd, _thread=t)

