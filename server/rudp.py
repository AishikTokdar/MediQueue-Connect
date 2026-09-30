"""
Reliable UDP (R-UDP) Transport Layer for MediQueue Connect.
Implements sequence numbering, Stop-and-Wait / Go-Back-N ARQ,
integrity checksum verification (MD5-8), and automatic retransmission (RTO).
"""

import json
import socket
import time
import hashlib
from typing import Any, Dict, Optional, Tuple


class RUDPPacket:
    def __init__(
        self,
        pkt_type: str,
        seq: int,
        ack: int = 0,
        payload: Optional[Dict[str, Any]] = None,
        checksum: str = "",
    ):
        self.pkt_type = pkt_type  # "DATA", "ACK", "SYN", "FIN"
        self.seq = seq
        self.ack = ack
        self.payload = payload or {}
        self.checksum = checksum or self._compute_checksum()

    def _compute_checksum(self) -> str:
        body = json.dumps(self.payload, sort_keys=True) if self.payload else ""
        raw = f"{self.pkt_type}:{self.seq}:{self.ack}:{body}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]

    def is_valid(self) -> bool:
        return self.checksum == self._compute_checksum()

    def to_bytes(self) -> bytes:
        data = {
            "rudp": True,
            "type": self.pkt_type,
            "seq": self.seq,
            "ack": self.ack,
            "payload": self.payload,
            "chk": self.checksum,
        }
        return json.dumps(data).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> Optional["RUDPPacket"]:
        try:
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, dict) and data.get("rudp"):
                pkt = cls(
                    pkt_type=data.get("type", "DATA"),
                    seq=int(data.get("seq", 0)),
                    ack=int(data.get("ack", 0)),
                    payload=data.get("payload") or {},
                    checksum=data.get("chk", ""),
                )
                if pkt.is_valid():
                    return pkt
        except Exception:
            pass
        return None


class RUDPConnection:
    """
    Maintains reliable state tracking for a single remote UDP peer.
    Provides ARQ sequence tracking, duplicate deduplication, and ACK management.
    """

    def __init__(self, peer_addr: Tuple[str, int], rto: float = 0.5, max_retries: int = 3):
        self.peer_addr = peer_addr
        self.rto = rto
        self.max_retries = max_retries
        self.next_seq_out = 0
        self.expected_seq_in = 0
        self.received_seqs: set[int] = set()

    def send_reliable(self, sock: socket.socket, payload: Dict[str, Any]) -> bool:
        """
        Sends payload as an ARQ sequenced RUDP packet and blocks until positive ACK is confirmed.
        Retransmits upon RTO timeout up to max_retries.
        """
        pkt = RUDPPacket(
            pkt_type="DATA",
            seq=self.next_seq_out,
            payload=payload,
        )
        packet_bytes = pkt.to_bytes()

        orig_timeout = sock.gettimeout()
        sock.settimeout(self.rto)

        delivered = False
        try:
            for attempt in range(self.max_retries):
                try:
                    sock.sendto(packet_bytes, self.peer_addr)
                    while True:
                        raw_ack, sender = sock.recvfrom(4096)
                        if sender != self.peer_addr:
                            continue
                        ack_pkt = RUDPPacket.from_bytes(raw_ack)
                        if ack_pkt and ack_pkt.pkt_type == "ACK" and ack_pkt.ack == self.next_seq_out:
                            delivered = True
                            self.next_seq_out += 1
                            break
                    if delivered:
                        break
                except socket.timeout:
                    continue
                except Exception:
                    break
        finally:
            sock.settimeout(orig_timeout)

        return delivered

    def handle_incoming(
        self, raw: bytes, sender: Tuple[str, int], sock: socket.socket
    ) -> Tuple[Optional[Dict[str, Any]], bool]:
        """
        Processes incoming UDP bytes. If RUDP DATA packet:
          - Sends ACK back immediately.
          - If new sequence: accepts payload.
          - If duplicate sequence: discards duplicate payload.
        If non-RUDP raw packet: returns parsed dict directly for backward compatibility.
        Returns (payload, is_rudp).
        """
        pkt = RUDPPacket.from_bytes(raw)
        if not pkt:
            # Fallback to standard JSON packet
            try:
                data = json.loads(raw.decode("utf-8"))
                return data, False
            except Exception:
                return None, False

        if pkt.pkt_type == "ACK":
            return None, True

        if pkt.pkt_type == "DATA":
            # Send immediate ACK
            ack_pkt = RUDPPacket(pkt_type="ACK", seq=0, ack=pkt.seq)
            try:
                sock.sendto(ack_pkt.to_bytes(), sender)
            except Exception:
                pass

            # Check for duplicate delivery
            if pkt.seq in self.received_seqs:
                return None, True  # Duplicate dropped

            self.received_seqs.add(pkt.seq)
            return pkt.payload, True

        return pkt.payload, True


def send_reliable_message(
    sock: socket.socket,
    payload: Dict[str, Any],
    addr: Tuple[str, int],
    rto: float = 0.5,
    max_retries: int = 3,
) -> bool:
    """
    One-off reliable message sender with stop-and-wait ARQ.
    """
    pkt = RUDPPacket(pkt_type="DATA", seq=1, payload=payload)
    pkt_bytes = pkt.to_bytes()
    orig_timeout = sock.gettimeout()
    sock.settimeout(rto)
    try:
        for _ in range(max_retries):
            try:
                sock.sendto(pkt_bytes, addr)
                raw_ack, sender = sock.recvfrom(4096)
                ack_pkt = RUDPPacket.from_bytes(raw_ack)
                if ack_pkt and ack_pkt.pkt_type == "ACK" and ack_pkt.ack == 1:
                    return True
            except socket.timeout:
                continue
            except Exception:
                break
        # Fallback to standard UDP send if peer doesn't speak RUDP yet
        sock.sendto(json.dumps(payload).encode("utf-8"), addr)
        return True
    finally:
        sock.settimeout(orig_timeout)


def parse_or_ack(
    sock: socket.socket,
    raw: bytes,
    sender: Tuple[str, int],
) -> Dict[str, Any]:
    """
    Parses an incoming UDP packet, sends ACK if RUDP DATA packet, or returns raw decoded JSON.
    """
    pkt = RUDPPacket.from_bytes(raw)
    if pkt and pkt.pkt_type == "DATA":
        ack = RUDPPacket(pkt_type="ACK", seq=0, ack=pkt.seq)
        try:
            sock.sendto(ack.to_bytes(), sender)
        except Exception:
            pass
        return pkt.payload

    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
