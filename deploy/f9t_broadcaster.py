#!/usr/bin/env python3
"""Single-reader broadcast server for the F9T's RTCM 3 stream.

Replaces the `socat -u FILE:/dev/gnss0 TCP-LISTEN:2101,fork` pattern,
which had a subtle bug for multi-consumer setups: socat's `fork` flag
spawns a new socat child per accepted TCP client, and each child opens
its own FILE:/dev/gnss0 reader.  Multiple readers of the same Linux
char device do NOT receive duplicated bytes — they SPLIT the byte
stream non-deterministically, with some bytes lost in race conditions.

Concrete impact (measured 2026-04-27 on ptpmon):
    - /dev/gnss0 raw rate: 617 B/s
    - 1 consumer connected: 633 B/s ✓
    - 2 consumers connected: 194 B/s each + dropped bytes ✗

This script reads /dev/gnss0 in a single thread, then broadcasts each
chunk to every currently-connected TCP client.  Each client gets the
FULL byte stream from the moment they connect onward.  No splitting,
no dropped bytes between readers (the kernel char device serves one
reader; multi-client fan-out happens in userspace).

Drop-in replacement for the socat command line in
f9t-tcp-bridge-ptpmon.service.

Stdlib only.

Usage:
    f9t_broadcaster.py [--device /dev/gnss0] [--listen-host 127.0.0.1]
                       [--listen-port 2101] [--read-chunk 4096]
"""
from __future__ import annotations

import argparse
import os
import select
import signal
import socket
import sys
import threading
from typing import Set


class Broadcaster:
    """Single /dev/gnss0 reader, multi-TCP-client fan-out."""

    def __init__(self, device: str, listen_host: str, listen_port: int,
                 read_chunk: int = 4096):
        self.device = device
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.read_chunk = read_chunk
        self._clients: Set[socket.socket] = set()
        self._clients_lock = threading.Lock()
        self._stop = threading.Event()

    def add_client(self, sock: socket.socket) -> None:
        sock.setblocking(False)  # don't let a slow client block reader
        with self._clients_lock:
            self._clients.add(sock)
        peer = sock.getpeername() if sock.fileno() >= 0 else "(closed)"
        print(f"client connected: {peer}; total {len(self._clients)}",
              flush=True)

    def remove_client(self, sock: socket.socket, why: str = "") -> None:
        with self._clients_lock:
            if sock not in self._clients:
                return
            self._clients.discard(sock)
        try:
            peer = sock.getpeername()
        except OSError:
            peer = "(closed)"
        print(f"client gone: {peer} ({why}); total {len(self._clients)}",
              flush=True)
        try:
            sock.close()
        except OSError:
            pass

    def broadcast(self, chunk: bytes) -> None:
        # Take a snapshot of the client set so we don't hold the lock
        # while doing send() (which can block if a client is slow, even
        # in non-blocking mode it can return BlockingIOError).
        with self._clients_lock:
            clients = list(self._clients)
        for sock in clients:
            try:
                sock.send(chunk)
            except BlockingIOError:
                # Slow client; drop the chunk for that client only.
                # An NTRIP/raw consumer that can't keep up at <1 kB/s
                # is unusable anyway.
                pass
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                self.remove_client(sock, why=f"send: {exc}")

    def reader_loop(self) -> None:
        """Single-threaded reader of /dev/gnss0; broadcast to clients."""
        fd = os.open(self.device, os.O_RDONLY)
        print(f"reading {self.device}", flush=True)
        try:
            while not self._stop.is_set():
                # select() with timeout so we can check stop flag periodically.
                r, _, _ = select.select([fd], [], [], 1.0)
                if not r:
                    continue
                chunk = os.read(fd, self.read_chunk)
                if not chunk:
                    print(f"{self.device} returned EOF; restarting",
                          file=sys.stderr, flush=True)
                    return
                self.broadcast(chunk)
        finally:
            os.close(fd)

    def accept_loop(self) -> None:
        """TCP accept loop; new clients added to the broadcast set."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.listen_host, self.listen_port))
        srv.listen(8)
        srv.settimeout(1.0)  # so we can check stop flag periodically
        print(f"listening on {self.listen_host}:{self.listen_port}",
              flush=True)
        try:
            while not self._stop.is_set():
                try:
                    sock, _ = srv.accept()
                except socket.timeout:
                    continue
                self.add_client(sock)
        finally:
            srv.close()

    def run(self) -> int:
        # Both loops run concurrently; reader thread does the broadcast,
        # accept thread adds clients to the shared set.
        reader = threading.Thread(target=self.reader_loop, daemon=True,
                                  name="reader")
        accept = threading.Thread(target=self.accept_loop, daemon=True,
                                  name="accept")
        reader.start()
        accept.start()

        # Install signal handlers for clean shutdown.
        def _sig(_signo, _frame):
            self._stop.set()
        signal.signal(signal.SIGINT, _sig)
        signal.signal(signal.SIGTERM, _sig)

        # Wait for shutdown.
        while not self._stop.is_set():
            self._stop.wait(timeout=2.0)
            # If reader thread exits (EOF or error), restart by exiting
            # — systemd's Restart=always handles the reconnect.
            if not reader.is_alive():
                print("reader thread exited; broadcaster will restart",
                      file=sys.stderr, flush=True)
                return 1
        return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--device", default="/dev/gnss0")
    p.add_argument("--listen-host", default="127.0.0.1")
    p.add_argument("--listen-port", type=int, default=2101)
    p.add_argument("--read-chunk", type=int, default=4096)
    args = p.parse_args()

    b = Broadcaster(
        device=args.device,
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        read_chunk=args.read_chunk,
    )
    return b.run()


if __name__ == "__main__":
    sys.exit(main())
