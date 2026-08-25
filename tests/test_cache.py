import os
import sys
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from cache import CacheManager


def test_cache_manager_session():
    cm = CacheManager()
    token = "test_cache_token_123"
    user = "cache_test_patient"

    cm.set_session(token, user, ttl=2)
    assert cm.get_session(token) == user

    cm.delete_session(token)
    assert cm.get_session(token) is None


def test_cache_manager_slots():
    cm = CacheManager()
    key = "insuranceA:Cardiology"
    data = {"Dr. Test": {"slots": ["9AM", "10AM"]}}

    cm.set_slots_cache(key, data, ttl=10)
    assert cm.get_slots_cache(key) == data

    cm.invalidate_slots_cache()
    assert cm.get_slots_cache(key) is None
