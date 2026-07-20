import socket
import threading
import time
import json
import statistics
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crypto_utils import wrap_client_socket

HOST = "127.0.0.1"
SERVER_PORT = 4000
UDP_ECHO_PORT = 5999

_echo_ready = threading.Event()


def parse_args():
    p = argparse.ArgumentParser(description="TCP vs UDP performance analysis")
    p.add_argument("--rounds", type=int, default=30, help="Number of round-trips per protocol (default: 30)")
    p.add_argument("--payload", type=int, default=64, help="UDP payload size in bytes (default: 64)")
    return p.parse_args()


def _udp_echo_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, UDP_ECHO_PORT))
    s.settimeout(30.0)
    _echo_ready.set()
    try:
        while True:
            try:
                data, addr = s.recvfrom(65535)
                s.sendto(data, addr)
            except socket.timeout:
                break
    finally:
        s.close()


def measure_tcp(rounds: int) -> list[float]:
    latencies = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((HOST, SERVER_PORT))
        sock = wrap_client_socket(sock, server_hostname=HOST)
    except ConnectionRefusedError:
        print("[ERROR] Cannot connect to Health Server – make sure health_server.py is running.")
        return latencies

    # Intentionally failing login so we don't pollute the session table.
    payload = (json.dumps({
        "command": "LOGIN",
        "username": "perf_test_user",
        "password": "wrong_password",
    }) + "\n").encode()

    for _ in range(rounds):
        t0 = time.perf_counter()
        sock.sendall(payload)
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000)

    sock.close()
    return latencies


def measure_udp(rounds: int, payload_size: int) -> list[float]:
    latencies = []
    payload = b"X" * payload_size
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    target = (HOST, UDP_ECHO_PORT)

    for _ in range(rounds):
        t0 = time.perf_counter()
        sock.sendto(payload, target)
        try:
            sock.recvfrom(65535)
        except socket.timeout:
            continue
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000)

    sock.close()
    return latencies


def stats(data: list[float]) -> dict:
    if not data:
        return {"mean": 0, "min": 0, "max": 0, "median": 0, "stdev": 0}
    return {
        "mean":   statistics.mean(data),
        "min":    min(data),
        "max":    max(data),
        "median": statistics.median(data),
        "stdev":  statistics.stdev(data) if len(data) > 1 else 0.0,
    }


def bar(value: float, max_val: float, width: int = 30) -> str:
    filled = int(round(value / max_val * width)) if max_val else 0
    return "#" * filled + "-" * (width - filled)


def print_table(tcp_lat: list[float], udp_lat: list[float]) -> None:
    print(f"\n{'Round':>6}  {'TCP (ms)':>10}  {'UDP (ms)':>10}")
    print("-" * 32)
    for i, (t, u) in enumerate(zip(tcp_lat, udp_lat), 1):
        print(f"{i:>6}  {t:>10.3f}  {u:>10.3f}")


def print_summary(tcp_s: dict, udp_s: dict) -> None:
    print(f"\n{'='*55}")
    print(f"  PERFORMANCE SUMMARY")
    print(f"{'='*55}")
    print(f"  {'Metric':12}  {'TCP (ms)':>12}  {'UDP (ms)':>12}")
    print(f"  {'-'*42}")
    for key in ("mean", "median", "min", "max", "stdev"):
        print(f"  {key:12}  {tcp_s[key]:>12.3f}  {udp_s[key]:>12.3f}")
    print(f"{'='*55}")

    max_mean = max(tcp_s["mean"], udp_s["mean"]) or 1
    print(f"\n  Mean latency comparison (bar = relative):\n")
    print(f"  TCP  [{bar(tcp_s['mean'], max_mean)}]  {tcp_s['mean']:.3f} ms")
    print(f"  UDP  [{bar(udp_s['mean'], max_mean)}]  {udp_s['mean']:.3f} ms")

    winner = "UDP" if udp_s["mean"] < tcp_s["mean"] else "TCP"
    diff = abs(tcp_s["mean"] - udp_s["mean"])
    print(f"\n  -> {winner} is faster by {diff:.3f} ms on average.\n")


def save_results(tcp_lat: list[float], udp_lat: list[float],
                 tcp_s: dict, udp_s: dict, payload_size: int) -> None:
    out_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "perf_results.json"
    )
    result = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "payload_bytes": payload_size,
        "tcp": {"latencies_ms": tcp_lat, "stats": tcp_s},
        "udp": {"latencies_ms": udp_lat, "stats": udp_s},
    }
    with open(out_path, "w") as f:
        json.dump(result, f, indent=4)
    print(f"  Results saved to: {out_path}")


def main():
    args = parse_args()
    rounds = args.rounds
    payload_size = args.payload

    print(f"\n{'='*55}")
    print(f"  TCP vs UDP Performance Analysis")
    print(f"  Rounds: {rounds}   UDP payload: {payload_size} bytes")
    print(f"{'='*55}\n")

    echo_thread = threading.Thread(target=_udp_echo_server, daemon=True)
    echo_thread.start()
    _echo_ready.wait(timeout=3)
    print("  [UDP echo server ready]")

    print(f"  Measuring TCP latency ({rounds} rounds)...")
    tcp_lat = measure_tcp(rounds)

    print(f"  Measuring UDP latency ({rounds} rounds, {payload_size}B payload)...")
    udp_lat = measure_udp(rounds, payload_size)

    if not tcp_lat:
        print("\n  Could not collect TCP latency data. Is the server running?")
        return

    # Trim to equal length in case UDP dropped some packets.
    min_len = min(len(tcp_lat), len(udp_lat))
    tcp_lat = tcp_lat[:min_len]
    udp_lat = udp_lat[:min_len]

    tcp_s = stats(tcp_lat)
    udp_s = stats(udp_lat)

    print_table(tcp_lat, udp_lat)
    print_summary(tcp_s, udp_s)
    save_results(tcp_lat, udp_lat, tcp_s, udp_s, payload_size)


if __name__ == "__main__":
    main()
