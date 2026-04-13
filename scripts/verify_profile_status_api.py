#!/usr/bin/env python3

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from server import (  # noqa: E402
    PROFILE_STATUS_CACHE,
    PROFILE_STATUS_CACHE_LOCK,
    classify_instagram_profile_payload,
    classify_instagram_profile_response,
    get_cached_profile_status,
    get_profile_status_cache_ttl_seconds,
    normalize_username,
    store_cached_profile_status,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_normalize_username():
    assert_equal(normalize_username("  Test_User  "), "test_user", "normalize_username")


def test_active_profile_payload_detection():
    payload = {
        "data": {
            "user": {
                "full_name": "Example User",
                "is_private": False,
                "username": "example_user",
            }
        }
    }
    result = classify_instagram_profile_payload("example_user", payload)
    assert_equal(result["status"], "active", "active profile")


def test_unavailable_profile_detection():
    body = "<html><body>Sorry, this page isn't available.</body></html>"
    result = classify_instagram_profile_response("gone_user", 200, "https://www.instagram.com/gone_user/", body)
    assert_equal(result["status"], "unavailable", "unavailable profile")


def test_rate_limited_detection():
    body = "<html><body>Please wait a few minutes before you try again.</body></html>"
    result = classify_instagram_profile_response("slow_user", 429, "https://www.instagram.com/slow_user/", body)
    assert_equal(result["status"], "rate_limited", "rate limited profile")


def test_login_wall_detection():
    body = "<html><body><div id='loginForm'>Log in</div></body></html>"
    result = classify_instagram_profile_response("private_user", 200, "https://www.instagram.com/accounts/login/", body)
    assert_equal(result["status"], "unknown", "login wall profile")


def test_cache_policy():
    assert_equal(get_profile_status_cache_ttl_seconds("active"), 24 * 60 * 60, "active cache ttl")
    assert_equal(get_profile_status_cache_ttl_seconds("unavailable"), 24 * 60 * 60, "unavailable cache ttl")
    assert_equal(get_profile_status_cache_ttl_seconds("unknown"), 6 * 60 * 60, "unknown cache ttl")
    assert_equal(get_profile_status_cache_ttl_seconds("rate_limited"), 10 * 60, "rate limit cache ttl")

    with PROFILE_STATUS_CACHE_LOCK:
        PROFILE_STATUS_CACHE.clear()

    stored = store_cached_profile_status(
        {
            "checkedAt": "2026-04-13T00:00:00+00:00",
            "detail": "공개 계정",
            "httpStatus": 200,
            "reason": "활성 계정으로 확인",
            "status": "active",
            "username": "Example_User",
        }
    )
    cached = get_cached_profile_status("example_user")

    assert_equal(stored["cached"], False, "fresh cache write")
    assert_equal(cached["cached"], True, "cached cache read")
    assert_equal(cached["status"], "active", "cached status")
    assert_equal(cached["username"], "example_user", "cached username")


def main():
    test_normalize_username()
    test_active_profile_payload_detection()
    test_unavailable_profile_detection()
    test_rate_limited_detection()
    test_login_wall_detection()
    test_cache_policy()
    print("Profile status classifier checks passed.")


if __name__ == "__main__":
    main()
