from __future__ import annotations

import argparse
import os
import socket
import struct
import sys
from pathlib import Path


def _request(socket_path: Path, command: str) -> bytes:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(socket_path))
        client.sendall(command.encode() + b"\n")
        return client.recv(64 * 1024)


def _serve(secret: str, socket_path: Path, pid_path: Path, ready_fd: int) -> None:
    socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(socket_path.parent, 0o700)
    socket_path.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    os.chmod(socket_path, 0o600)
    server.listen(4)
    pid_path.write_text(f"{os.getpid()}\n", encoding="ascii")
    os.chmod(pid_path, 0o600)
    os.write(ready_fd, b"1")
    os.close(ready_fd)
    try:
        while True:
            connection, _ = server.accept()
            with connection:
                peer_pid, peer_uid, _ = struct.unpack(
                    "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                )
                if peer_uid != os.getuid() or peer_pid <= 0:
                    connection.sendall(b"DENIED\n")
                    continue
                command = connection.recv(64).strip()
                if command == b"GET":
                    connection.sendall(secret.encode() + b"\n")
                elif command == b"STATUS":
                    connection.sendall(b"AVAILABLE\n")
                elif command == b"STOP":
                    connection.sendall(b"STOPPED\n")
                    break
                else:
                    connection.sendall(b"INVALID\n")
    finally:
        secret = ""
        server.close()
        socket_path.unlink(missing_ok=True)
        pid_path.unlink(missing_ok=True)


def start(secret: str, socket_path: Path, pid_path: Path) -> None:
    if socket_path.exists():
        try:
            _request(socket_path, "STOP")
        except OSError:
            socket_path.unlink(missing_ok=True)
    read_fd, write_fd = os.pipe()
    first_pid = os.fork()
    if first_pid:
        os.close(write_fd)
        ready = os.read(read_fd, 1)
        os.close(read_fd)
        os.waitpid(first_pid, 0)
        if ready != b"1":
            raise RuntimeError("camera secret agent did not start")
        return
    os.close(read_fd)
    os.setsid()
    second_pid = os.fork()
    if second_pid:
        os._exit(0)
    null_fd = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(null_fd, fd)
    if null_fd > 2:
        os.close(null_fd)
    try:
        _serve(secret, socket_path, pid_path, write_fd)
    finally:
        os._exit(0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("start", "get", "status", "stop"))
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--pid", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "start":
        secret = sys.stdin.readline().strip()
        if not secret.startswith("rtsp://"):
            print("ERROR: secret must be an RTSP URI", file=sys.stderr)
            return 1
        start(secret, args.socket, args.pid)
        secret = ""
        print("camera_secret_agent=available")
        return 0
    try:
        response = _request(args.socket, args.command.upper())
    except OSError:
        if args.command == "status":
            print("camera_secret_agent=missing")
        return 1
    if args.command == "get":
        sys.stdout.buffer.write(response)
    else:
        print(response.decode().strip().lower())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
