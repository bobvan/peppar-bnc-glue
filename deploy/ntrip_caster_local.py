#!/usr/bin/env python3
"""Minimal local NTRIP caster — fronts a raw RTCM TCP source.

BNC's PPP module accepts NTRIP streams or RINEX files as PPP input;
no "raw TCP" option.  Our F9T is exposed on localhost:2101 as a
plain RTCM-3 byte stream by socat.  This script wraps that stream
with the NTRIP/1.0 protocol so BNC can connect to it as if it were
a real caster.

Architecture (ptpmon-local):

   F9T  ──►  /dev/gnss0  ──socat──►  localhost:2101 (raw bytes)
                                            │
                                            ▼
                            ntrip_caster_local.py
                                            │
                                            ▼  NTRIP/1.0
                                      localhost:2102/F9T_PTPMON
                                            │
                                            ▼
                                          BNC

Multiple BNC instances (or other clients) can connect concurrently;
each gets its own copy of the byte stream from the upstream socat
TCP server.

This is intentionally minimal — no auth (loopback only — bind to
127.0.0.1), no source-table negotiation beyond what BNC needs,
no historical replay.  Production NTRIP casters are vastly more
sophisticated.

Stdlib only — runs in any Python 3.10+.
"""

from __future__ import annotations

import argparse
import socket
import socketserver
import sys
import threading
import time
from typing import Optional


SOURCETABLE_FMT = (
    "STR;{mount};F9T_PTPMON;RTCM 3.3;1077(1),1097(1),1127(1),1005(5),1230(5);"
    "0;NONE;NONE;38.00;-122.00;0;0;peppar-bnc-glue;NONE;B;N;1024;\r\n"
    "ENDSOURCETABLE\r\n"
)


class CasterHandler(socketserver.StreamRequestHandler):

    def handle(self) -> None:
        cfg: ServerConfig = self.server.cfg  # type: ignore[attr-defined]
        try:
            req = self.rfile.readline(1024).decode("ascii", errors="replace").rstrip("\r\n")
        except Exception:
            return
        # Drain the rest of the headers (we don't actually authenticate).
        while True:
            line = self.rfile.readline(1024)
            if line in (b"", b"\r\n", b"\n"):
                break

        # NTRIP/1.0 GET request:  GET /MOUNT HTTP/1.0
        # Source-table request:    GET / HTTP/1.0
        parts = req.split()
        if len(parts) < 2 or parts[0] != "GET":
            self._respond_400()
            return
        path = parts[1].lstrip("/")

        if path == "" or path == "?STR=" or path.lower().startswith("?str="):
            self._respond_sourcetable(cfg.mount)
            return

        if path != cfg.mount:
            self._respond_404(cfg.mount)
            return

        # Mount request — open upstream TCP connection, stream bytes.
        try:
            up = socket.create_connection((cfg.upstream_host, cfg.upstream_port), timeout=5)
        except Exception as exc:
            self._respond_503(str(exc))
            return

        try:
            self.wfile.write(b"ICY 200 OK\r\n\r\n")
            self.wfile.flush()
            self._pump(up)
        finally:
            try:
                up.close()
            except Exception:
                pass

    def _pump(self, up: socket.socket) -> None:
        # Forward raw bytes from upstream to client until either side closes.
        up.settimeout(30.0)
        while True:
            try:
                chunk = up.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return
            try:
                self.wfile.write(chunk)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

    def _respond_sourcetable(self, mount: str) -> None:
        body = SOURCETABLE_FMT.format(mount=mount)
        self.wfile.write(b"SOURCETABLE 200 OK\r\n")
        self.wfile.write(b"Server: peppar-bnc-glue NTRIP local 1.0\r\n")
        self.wfile.write(f"Content-Length: {len(body)}\r\n".encode("ascii"))
        self.wfile.write(b"Content-Type: text/plain\r\n\r\n")
        self.wfile.write(body.encode("ascii"))

    def _respond_404(self, mount: str) -> None:
        self.wfile.write(b"HTTP/1.0 404 Not Found\r\n\r\n")
        self.wfile.write(f"only mount /{mount} is available\r\n".encode("ascii"))

    def _respond_400(self) -> None:
        self.wfile.write(b"HTTP/1.0 400 Bad Request\r\n\r\n")

    def _respond_503(self, why: str) -> None:
        self.wfile.write(b"HTTP/1.0 503 Service Unavailable\r\n\r\n")
        self.wfile.write(why.encode("ascii", errors="replace"))


class ThreadingCaster(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class ServerConfig:
    def __init__(self, mount: str, upstream_host: str, upstream_port: int) -> None:
        self.mount = mount
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--listen-host", default="127.0.0.1")
    p.add_argument("--listen-port", type=int, default=2102)
    p.add_argument("--upstream-host", default="127.0.0.1")
    p.add_argument("--upstream-port", type=int, default=2101)
    p.add_argument("--mount", default="F9T_PTPMON")
    args = p.parse_args()

    print(
        f"NTRIP caster: listening on {args.listen_host}:{args.listen_port}, "
        f"mount /{args.mount}, upstream {args.upstream_host}:{args.upstream_port}",
        flush=True,
    )

    server = ThreadingCaster((args.listen_host, args.listen_port), CasterHandler)
    server.cfg = ServerConfig(  # type: ignore[attr-defined]
        mount=args.mount,
        upstream_host=args.upstream_host,
        upstream_port=args.upstream_port,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
