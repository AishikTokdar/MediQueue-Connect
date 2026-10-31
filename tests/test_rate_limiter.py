import asyncio
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from health_server import RateLimiter


def test_rate_limiter_allow_under_capacity():
    asyncio.run(_test_rate_limiter_allow_under_capacity())


async def _test_rate_limiter_allow_under_capacity():
    rl = RateLimiter(rate=5.0, capacity=10.0, ban_time=1.0)
    client_ip = "192.168.1.100"

    # Consume 5 tokens in quick succession (under capacity of 10)
    for _ in range(5):
        allowed = await rl.allow(client_ip)
        assert allowed is True

    assert client_ip not in await rl.get_banned_ips()


def test_rate_limiter_ban_on_exhaustion():
    asyncio.run(_test_rate_limiter_ban_on_exhaustion())


async def _test_rate_limiter_ban_on_exhaustion():
    # Small capacity to easily trigger ban
    rl = RateLimiter(rate=1.0, capacity=2.0, ban_time=0.5)
    attacker_ip = "10.0.0.99"

    assert await rl.allow(attacker_ip) is True   # Token 1
    assert await rl.allow(attacker_ip) is True   # Token 2
    assert await rl.allow(attacker_ip) is False  # Exceeded -> Banned!

    banned_list = await rl.get_banned_ips()
    assert attacker_ip in banned_list

    # Unban IP manually
    assert await rl.unban(attacker_ip) is True
    assert attacker_ip not in await rl.get_banned_ips()
