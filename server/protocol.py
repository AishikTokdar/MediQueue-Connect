import json
import socket
import struct
import asyncio
from typing import Any, Dict, Optional

HEADER_FORMAT = ">I"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


def send_framed(sock: socket.socket, payload: Dict[str, Any]) -> None:
    data = json.dumps(payload).encode("utf-8")
    length = len(data)
    header = struct.pack(HEADER_FORMAT, length)
    sock.sendall(header + data)


def recv_framed(sock: socket.socket) -> Optional[Dict[str, Any]]:
    header_data = _recv_exact(sock, HEADER_SIZE)
    if not header_data:
        return None

    # Check for legacy raw JSON newline protocol (if first byte is '{' or non-binary)
    if header_data[0:1] == b"{" or header_data[0:1] == b" ":
        # Raw json chunk: read until newline
        rest = _recv_until_newline(sock)
        full_line = header_data + rest
        try:
            return json.loads(full_line.decode("utf-8"))
        except Exception:
            return None

    length = struct.unpack(HEADER_FORMAT, header_data)[0]
    if length > 10 * 1024 * 1024:  # 10MB safety cap
        raise ValueError("Payload size exceeds maximum safety limit (10MB)")

    body_data = _recv_exact(sock, length)
    if not body_data:
        return None

    return json.loads(body_data.decode("utf-8"))


def _recv_exact(sock: socket.socket, num_bytes: int) -> Optional[bytes]:
    buf = bytearray()
    while len(buf) < num_bytes:
        try:
            chunk = sock.recv(num_bytes - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        except (socket.error, ConnectionResetError):
            return None
    return bytes(buf)


def _recv_until_newline(sock: socket.socket) -> bytes:
    buf = bytearray()
    while True:
        try:
            chunk = sock.recv(1)
            if not chunk or chunk == b"\n":
                break
            buf.extend(chunk)
        except Exception:
            break
    return bytes(buf)


async def async_send_framed(writer: asyncio.StreamWriter, payload: Dict[str, Any]) -> None:
    data = json.dumps(payload).encode("utf-8")
    length = len(data)
    header = struct.pack(HEADER_FORMAT, length)
    writer.write(header + data)
    await writer.drain()


async def async_recv_framed(reader: asyncio.StreamReader) -> Optional[Dict[str, Any]]:
    try:
        header_data = await reader.readexactly(HEADER_SIZE)
    except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
        return None

    # Fallback for legacy raw JSON newline protocol
    if header_data[0:1] == b"{" or header_data[0:1] == b" ":
        rest = await reader.readline()
        full_line = header_data + rest
        try:
            return json.loads(full_line.decode("utf-8"))
        except Exception:
            return None

    length = struct.unpack(HEADER_FORMAT, header_data)[0]
    if length > 10 * 1024 * 1024:
        raise ValueError("Payload size exceeds maximum safety limit (10MB)")

    try:
        body_data = await reader.readexactly(length)
    except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
        return None

    return json.loads(body_data.decode("utf-8"))
