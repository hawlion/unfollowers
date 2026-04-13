#!/usr/bin/env python3

import io
import json
import re
import zipfile
from pathlib import Path

FOLLOWERS_PATH_RE = re.compile(r"^connections/followers_and_following/followers_(\d+)\.json$")
FOLLOWING_PATH = "connections/followers_and_following/following.json"
RECENTLY_UNFOLLOWED_PATH = "connections/followers_and_following/recently_unfollowed_profiles.json"


def normalize_username(username):
    return str(username or "").strip().lower()


def make_entry(username, href=None, timestamp=None, source=""):
    normalized = normalize_username(username)

    if not normalized:
        return None

    return {
        "href": href or None,
        "normalizedUsername": normalized,
        "source": source,
        "timestamp": timestamp if isinstance(timestamp, (int, float)) else None,
        "username": str(username).strip(),
    }


def pick_entry(base_entry, next_entry):
    if base_entry is None:
        return dict(next_entry)

    base_time = base_entry["timestamp"] if isinstance(base_entry["timestamp"], (int, float)) else -1
    next_time = next_entry["timestamp"] if isinstance(next_entry["timestamp"], (int, float)) else -1

    if next_time > base_time:
        return {
            **base_entry,
            **next_entry,
            "href": next_entry["href"] or base_entry["href"],
            "timestamp": next_entry["timestamp"] if next_entry["timestamp"] is not None else base_entry["timestamp"],
            "username": next_entry["username"] or base_entry["username"],
        }

    return {
        **base_entry,
        "href": base_entry["href"] or next_entry["href"],
        "timestamp": base_entry["timestamp"] if base_entry["timestamp"] is not None else next_entry["timestamp"],
        "username": base_entry["username"] or next_entry["username"],
    }


def dedupe_entries(entries):
    deduped = {}

    for entry in entries:
        if not entry or not entry["normalizedUsername"]:
            continue

        current = deduped.get(entry["normalizedUsername"])
        deduped[entry["normalizedUsername"]] = pick_entry(current, entry)

    return list(deduped.values())


def sort_entries(entries):
    def sort_key(entry):
        timestamp = entry["timestamp"]
        has_timestamp = 0 if timestamp is not None else 1
        return (has_timestamp, -(timestamp or 0), entry["username"].lower())

    return sorted(entries, key=sort_key)


def parse_json_or_raise(payload, source):
    try:
        return json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(f"{source} JSON을 읽지 못했습니다.") from error


def parse_followers_json(payload, source):
    parsed = parse_json_or_raise(payload, source)

    if not isinstance(parsed, list):
        raise ValueError(f"{source} 형식이 예상과 다릅니다.")

    entries = []

    for item in parsed:
        for row in item.get("string_list_data", []):
            entry = make_entry(row.get("value"), row.get("href"), row.get("timestamp"), source)
            if entry:
                entries.append(entry)

    return entries


def parse_following_json(payload, source):
    parsed = parse_json_or_raise(payload, source)
    following = parsed.get("relationships_following")

    if not isinstance(following, list):
        raise ValueError(f"{source} 형식이 예상과 다릅니다.")

    entries = []

    for item in following:
        string_list = item.get("string_list_data") or []
        first_row = string_list[0] if string_list else {}
        entry = make_entry(item.get("title"), first_row.get("href"), first_row.get("timestamp"), source)
        if entry:
            entries.append(entry)

    return entries


def parse_recently_unfollowed_json(payload, source):
    parsed = parse_json_or_raise(payload, source)
    unfollowed = parsed.get("relationships_unfollowed_users")

    if not isinstance(unfollowed, list):
        raise ValueError(f"{source} 형식이 예상과 다릅니다.")

    entries = []

    for item in unfollowed:
        for row in item.get("string_list_data", []):
            entry = make_entry(row.get("value"), row.get("href"), row.get("timestamp"), source)
            if entry:
                entries.append(entry)

    return entries


def compare_entries(parsed_export):
    followers_by_username = {entry["normalizedUsername"]: entry for entry in parsed_export["followers"]}
    following_by_username = {entry["normalizedUsername"]: entry for entry in parsed_export["following"]}
    not_following_back = []
    followers_only = []
    mutual_count = 0

    for entry in parsed_export["following"]:
        if entry["normalizedUsername"] in followers_by_username:
            mutual_count += 1
        else:
            not_following_back.append(entry)

    for entry in parsed_export["followers"]:
        if entry["normalizedUsername"] not in following_by_username:
            followers_only.append(entry)

    recently_unfollowed = sort_entries(parsed_export["recentlyUnfollowed"])

    return {
        "followersOnly": sort_entries(followers_only),
        "mutualCount": mutual_count,
        "notFollowingBack": sort_entries(not_following_back),
        "recentlyUnfollowed": recently_unfollowed,
        "summaryCounts": {
            "followersCount": len(parsed_export["followers"]),
            "followingCount": len(parsed_export["following"]),
            "mutualCount": mutual_count,
            "notFollowingBackCount": len(not_following_back),
            "recentlyUnfollowedCount": len(recently_unfollowed),
        },
    }


def parse_export_zip_bytes(payload):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        follower_paths = sorted(
            (
                (int(match.group(1)), name)
                for name in names
                for match in [FOLLOWERS_PATH_RE.match(name)]
                if match
            ),
            key=lambda item: item[0],
        )

        missing = []
        if not follower_paths:
            missing.append("connections/followers_and_following/followers_*.json")
        if FOLLOWING_PATH not in names:
            missing.append(FOLLOWING_PATH)
        if missing:
            raise ValueError("필수 파일을 찾지 못했습니다: " + ", ".join(missing))

        followers = []
        for _, path in follower_paths:
            followers.extend(parse_followers_json(archive.read(path), path))

        following = parse_following_json(archive.read(FOLLOWING_PATH), FOLLOWING_PATH)
        recently_unfollowed = []
        has_recent_data = RECENTLY_UNFOLLOWED_PATH in names

        if has_recent_data:
            recently_unfollowed = parse_recently_unfollowed_json(
                archive.read(RECENTLY_UNFOLLOWED_PATH),
                RECENTLY_UNFOLLOWED_PATH,
            )

        parsed_export = {
            "followers": dedupe_entries(followers),
            "following": dedupe_entries(following),
            "recentlyUnfollowed": dedupe_entries(recently_unfollowed),
        }

        return {
            "comparison": compare_entries(parsed_export),
            "hasRecentData": has_recent_data,
        }


def build_followers_json(usernames):
    return [
        {
            "title": "",
            "media_list_data": [],
            "string_list_data": [
                {
                    "href": f"https://www.instagram.com/{username}",
                    "value": username,
                    "timestamp": timestamp,
                }
            ],
        }
        for username, timestamp in usernames
    ]


def build_following_json(usernames):
    return {
        "relationships_following": [
            {
                "title": username,
                "string_list_data": [
                    {
                        "href": f"https://www.instagram.com/_u/{username}",
                        "timestamp": timestamp,
                    }
                ],
            }
            for username, timestamp in usernames
        ]
    }


def build_recently_unfollowed_json(usernames):
    return {
        "relationships_unfollowed_users": [
            {
                "title": "",
                "media_list_data": [],
                "string_list_data": [
                    {
                        "href": f"https://www.instagram.com/{username}",
                        "value": username,
                        "timestamp": timestamp,
                    }
                ],
            }
            for username, timestamp in usernames
        ]
    }


def build_zip_bytes(followers_files, following_entries=None, recently_unfollowed_entries=None, malformed=None):
    buffer = io.BytesIO()
    malformed = malformed or {}

    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, usernames in enumerate(followers_files, start=1):
            followers_path = f"connections/followers_and_following/followers_{index}.json"
            if followers_path in malformed:
                continue
            archive.writestr(
                followers_path,
                json.dumps(build_followers_json(usernames)),
            )

        if following_entries is not None and FOLLOWING_PATH not in malformed:
            archive.writestr(
                FOLLOWING_PATH,
                json.dumps(build_following_json(following_entries)),
            )

        if recently_unfollowed_entries is not None and RECENTLY_UNFOLLOWED_PATH not in malformed:
            archive.writestr(
                RECENTLY_UNFOLLOWED_PATH,
                json.dumps(build_recently_unfollowed_json(recently_unfollowed_entries)),
            )

        for path, text in malformed.items():
            archive.writestr(path, text)

    return buffer.getvalue()


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_provided_export(zip_path):
    payload = Path(zip_path).read_bytes()
    result = parse_export_zip_bytes(payload)
    summary = result["comparison"]["summaryCounts"]

    assert_equal(summary["followersCount"], 2187, "followersCount")
    assert_equal(summary["followingCount"], 1539, "followingCount")
    assert_equal(summary["mutualCount"], 1475, "mutualCount")
    assert_equal(summary["notFollowingBackCount"], 64, "notFollowingBackCount")
    assert_equal(summary["recentlyUnfollowedCount"], 17, "recentlyUnfollowedCount")
    assert_equal(len(result["comparison"]["followersOnly"]), 712, "followersOnlyCount")
    assert_equal(result["hasRecentData"], True, "hasRecentData")


def test_multiple_followers_files_and_case_dedupe():
    payload = build_zip_bytes(
        followers_files=[
            [("Alpha", 10), ("Beta", 9)],
            [("ALPHA", 12), ("Gamma", 8)],
        ],
        following_entries=[("alpha", 11), ("delta", 7)],
        recently_unfollowed_entries=[("delta", 20)],
    )
    result = parse_export_zip_bytes(payload)
    summary = result["comparison"]["summaryCounts"]

    assert_equal(summary["followersCount"], 3, "deduped followers")
    assert_equal(summary["followingCount"], 2, "following count")
    assert_equal(summary["mutualCount"], 1, "mutual count")
    assert_equal(summary["notFollowingBackCount"], 1, "not following back count")
    assert_equal(summary["recentlyUnfollowedCount"], 1, "recently unfollowed count")
    assert_equal([entry["username"] for entry in result["comparison"]["followersOnly"]], ["Beta", "Gamma"], "followers only order")
    assert_equal(result["comparison"]["notFollowingBack"][0]["username"], "delta", "not following back username")


def test_all_mutual():
    payload = build_zip_bytes(
        followers_files=[[("one", 1), ("two", 2)]],
        following_entries=[("one", 3), ("two", 4)],
        recently_unfollowed_entries=[],
    )
    result = parse_export_zip_bytes(payload)
    summary = result["comparison"]["summaryCounts"]

    assert_equal(summary["notFollowingBackCount"], 0, "all mutual notFollowingBackCount")
    assert_equal(summary["mutualCount"], 2, "all mutual mutualCount")


def test_missing_recent_file():
    payload = build_zip_bytes(
        followers_files=[[("one", 1)]],
        following_entries=[("two", 2)],
        recently_unfollowed_entries=None,
    )
    result = parse_export_zip_bytes(payload)
    summary = result["comparison"]["summaryCounts"]

    assert_equal(result["hasRecentData"], False, "missing recent file flag")
    assert_equal(summary["recentlyUnfollowedCount"], 0, "missing recent file count")


def test_missing_required_file():
    payload = build_zip_bytes(
        followers_files=[[("one", 1)]],
        following_entries=None,
        recently_unfollowed_entries=[],
    )

    try:
        parse_export_zip_bytes(payload)
    except ValueError as error:
        assert FOLLOWING_PATH in str(error)
        return

    raise AssertionError("missing required file should fail")


def test_malformed_json():
    payload = build_zip_bytes(
        followers_files=[[("one", 1)]],
        following_entries=[("two", 2)],
        recently_unfollowed_entries=[],
        malformed={FOLLOWING_PATH: "{not-json"},
    )

    try:
        parse_export_zip_bytes(payload)
    except ValueError as error:
        assert "JSON을 읽지 못했습니다" in str(error)
        return

    raise AssertionError("malformed JSON should fail")


def main():
    provided_zip_path = Path("/Users/1110025/Downloads/instagram-leoinseoul-2026-04-12-BQgzWzDa.zip")

    test_multiple_followers_files_and_case_dedupe()
    test_all_mutual()
    test_missing_recent_file()
    test_missing_required_file()
    test_malformed_json()

    if provided_zip_path.exists():
        test_provided_export(provided_zip_path)
        print("All verification checks passed, including the provided export ZIP.")
        return

    print("All synthetic verification checks passed. Provided export ZIP was not found.")


if __name__ == "__main__":
    main()
