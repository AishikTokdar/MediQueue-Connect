"""
Encrypted Clinical File and Lab Report Transfer Module for MediQueue Connect.
Supports chunked transfer, Base64 encoding, Fernet session encryption,
and reassembly into data/attachments/<session_id>/<filename>.
"""

import os
import json
import base64
import time
from typing import Optional, Tuple, Dict, Any
from crypto_utils import encrypt_message, decrypt_message

CHUNK_SIZE = 1024  # 1 KB chunk size for datagram-safe transport
ATTACHMENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "attachments")


def send_file_stream(
    sock,
    peer_addr: Tuple[str, int],
    filepath: str,
    session_id: str,
    session_key: Optional[bytes] = None,
    send_fn=None,
) -> bool:
    """
    Reads file, fragments it into encrypted chunks, and dispatches them to the remote peer.
    """
    if not os.path.exists(filepath):
        print(f"  [ERROR] File not found: {filepath}")
        return False

    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        file_bytes = f.read()

    total_bytes = len(file_bytes)
    chunks = [file_bytes[i : i + CHUNK_SIZE] for i in range(0, total_bytes, CHUNK_SIZE)]
    total_chunks = len(chunks) or 1

    print(f"  [FILE TRANSFER] Sending '{filename}' ({total_bytes} bytes in {total_chunks} chunks)...")

    # Start notification
    start_payload = {
        "type": "FILE_START",
        "filename": filename,
        "filesize": total_bytes,
        "total_chunks": total_chunks,
        "session_id": session_id,
    }
    if send_fn:
        send_fn(sock, start_payload, peer_addr)
    else:
        sock.sendto(json.dumps(start_payload).encode("utf-8"), peer_addr)

    # Chunks
    for idx, chunk in enumerate(chunks, 1):
        b64_chunk = base64.b64encode(chunk).decode("ascii")
        if session_key:
            b64_chunk = encrypt_message(b64_chunk, session_key)

        chunk_payload = {
            "type": "FILE_CHUNK",
            "filename": filename,
            "chunk_idx": idx,
            "total_chunks": total_chunks,
            "data": b64_chunk,
            "session_id": session_id,
        }
        if send_fn:
            send_fn(sock, chunk_payload, peer_addr)
        else:
            sock.sendto(json.dumps(chunk_payload).encode("utf-8"), peer_addr)
        time.sleep(0.01)  # Flow control pause

    # Completion notification
    end_payload = {
        "type": "FILE_END",
        "filename": filename,
        "session_id": session_id,
    }
    if send_fn:
        send_fn(sock, end_payload, peer_addr)
    else:
        sock.sendto(json.dumps(end_payload).encode("utf-8"), peer_addr)

    print(f"  [FILE TRANSFER] '{filename}' dispatched successfully.")
    return True


class FileReceiver:
    """
    Stateful receiver that aggregates chunks and writes complete files to disk.
    """

    def __init__(self):
        self._buffers: Dict[str, Dict[str, Any]] = {}

    def process_packet(
        self, msg: Dict[str, Any], session_id: str, session_key: Optional[bytes] = None
    ) -> Optional[str]:
        """
        Processes FILE_START, FILE_CHUNK, or FILE_END.
        Returns the saved file path upon successful completion, or None.
        """
        msg_type = msg.get("type")
        filename = msg.get("filename", "unknown_file")
        buffer_key = f"{session_id}:{filename}"

        if msg_type == "FILE_START":
            self._buffers[buffer_key] = {
                "filename": filename,
                "filesize": msg.get("filesize", 0),
                "total_chunks": msg.get("total_chunks", 1),
                "chunks": {},
            }
            return None

        elif msg_type == "FILE_CHUNK":
            buf = self._buffers.get(buffer_key)
            if not buf:
                buf = {
                    "filename": filename,
                    "filesize": 0,
                    "total_chunks": msg.get("total_chunks", 1),
                    "chunks": {},
                }
                self._buffers[buffer_key] = buf

            raw_chunk_data = msg.get("data", "")
            if session_key:
                try:
                    raw_chunk_data = decrypt_message(raw_chunk_data, session_key)
                except Exception:
                    pass

            try:
                chunk_bytes = base64.b64decode(raw_chunk_data.encode("ascii"))
                buf["chunks"][msg.get("chunk_idx", 1)] = chunk_bytes
            except Exception:
                pass
            return None

        elif msg_type == "FILE_END":
            buf = self._buffers.pop(buffer_key, None)
            if not buf:
                return None

            chunks_map = buf.get("chunks", {})
            full_data = bytearray()
            for i in range(1, buf["total_chunks"] + 1):
                if i in chunks_map:
                    full_data.extend(chunks_map[i])

            target_dir = os.path.join(ATTACHMENTS_DIR, session_id)
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, filename)

            with open(target_path, "wb") as f:
                f.write(full_data)

            return target_path

        return None
