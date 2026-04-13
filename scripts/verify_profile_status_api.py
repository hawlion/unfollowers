#!/usr/bin/env python3

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from server import (  # noqa: E402
    classify_instagram_profile_payload,
    classify_instagram_profile_response,
    normalize_username,
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


def main():
    test_normalize_username()
    test_active_profile_payload_detection()
    test_unavailable_profile_detection()
    test_rate_limited_detection()
    test_login_wall_detection()
    print("Profile status classifier checks passed.")


if __name__ == "__main__":
    main()
