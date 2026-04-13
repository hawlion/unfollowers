#!/usr/bin/env python3

import argparse
import json
import os
import socket
import sys
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, build_opener

ROOT_DIR = Path(__file__).resolve().parent
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)
INSTAGRAM_APP_ID = "936619743392459"
MAX_BATCH_SIZE = 5
REQUEST_TIMEOUT_SECONDS = 10
INSTAGRAM_PROFILE_URL = "https://www.instagram.com/{username}/"
INSTAGRAM_WEB_PROFILE_INFO_URL = "https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
PROFILE_STATUS_CACHE_TTL_SECONDS = 24 * 60 * 60
PROFILE_STATUS_UNAVAILABLE_CACHE_TTL_SECONDS = 24 * 60 * 60
PROFILE_STATUS_UNKNOWN_CACHE_TTL_SECONDS = 6 * 60 * 60
PROFILE_STATUS_RATE_LIMIT_CACHE_TTL_SECONDS = 10 * 60
PAGE_NOT_AVAILABLE_HINTS = (
    "Sorry, this page isn't available.",
    "Page isn't available",
    "This page isn't available.",
    "The link you followed may be broken",
)
RATE_LIMIT_HINTS = (
    "Please wait a few minutes before you try again.",
    "Try Again Later",
)
LOGIN_HINTS = (
    "/accounts/login/",
    "loginForm",
    '"is_logged_out":true',
)
PROFILE_STATUS_CACHE = {}
PROFILE_STATUS_CACHE_LOCK = Lock()


def normalize_username(username):
    return str(username or "").strip().lower()


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def iso_from_timestamp(epoch_seconds):
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).isoformat()


def epoch_now():
    return datetime.now(timezone.utc).timestamp()


def get_profile_status_cache_ttl_seconds(status):
    if status == "rate_limited":
        return PROFILE_STATUS_RATE_LIMIT_CACHE_TTL_SECONDS

    if status == "unavailable":
        return PROFILE_STATUS_UNAVAILABLE_CACHE_TTL_SECONDS

    if status == "unknown":
        return PROFILE_STATUS_UNKNOWN_CACHE_TTL_SECONDS

    return PROFILE_STATUS_CACHE_TTL_SECONDS


def get_cached_profile_status(username):
    normalized = normalize_username(username)

    if not normalized:
        return None

    now = epoch_now()

    with PROFILE_STATUS_CACHE_LOCK:
        cached_entry = PROFILE_STATUS_CACHE.get(normalized)

        if not cached_entry:
            return None

        expires_at = cached_entry.get("expiresAtEpoch")

        if not isinstance(expires_at, (int, float)) or expires_at <= now:
            PROFILE_STATUS_CACHE.pop(normalized, None)
            return None

        result = dict(cached_entry.get("result") or {})

    result["cacheExpiresAt"] = iso_from_timestamp(expires_at)
    result["cached"] = True
    return result


def store_cached_profile_status(result):
    normalized = normalize_username(result.get("username"))

    if not normalized:
        return result

    ttl_seconds = get_profile_status_cache_ttl_seconds(result.get("status"))
    expires_at = epoch_now() + ttl_seconds
    cached_result = dict(result)
    cached_result["username"] = normalized

    with PROFILE_STATUS_CACHE_LOCK:
        PROFILE_STATUS_CACHE[normalized] = {
            "expiresAtEpoch": expires_at,
            "result": cached_result,
        }

    response = dict(cached_result)
    response["cacheExpiresAt"] = iso_from_timestamp(expires_at)
    response["cached"] = False
    return response


def fetch_or_get_cached_profile_status(username, opener=None):
    cached_result = get_cached_profile_status(username)

    if cached_result is not None:
        return cached_result

    return store_cached_profile_status(fetch_profile_status(username, opener=opener))


def classify_instagram_profile_payload(username, payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    user = data.get("user") if isinstance(data, dict) else None

    if not isinstance(user, dict):
        return {
            "detail": "user 데이터 없음",
            "reason": "활성 여부를 단정할 수 없음",
            "status": "unknown",
        }

    payload_username = normalize_username(user.get("username"))

    if payload_username and payload_username == normalize_username(username):
        full_name = str(user.get("full_name") or "").strip()
        is_private = bool(user.get("is_private"))
        detail_parts = []

        if full_name:
            detail_parts.append(full_name)

        detail_parts.append("비공개 계정" if is_private else "공개 계정")

        return {
            "detail": " / ".join(detail_parts),
            "reason": "활성 계정으로 확인",
            "status": "active",
        }

    return {
        "detail": "응답 username 불일치",
        "reason": "활성 여부를 단정할 수 없음",
        "status": "unknown",
    }


def classify_instagram_profile_response(username, http_status, final_url, body_text):
    normalized = normalize_username(username)
    final_url = final_url or ""
    body_text = body_text or ""
    lower_body = body_text.lower()
    lower_url = final_url.lower()

    if http_status == 404:
        return {
            "detail": "404 응답",
            "reason": "프로필 페이지가 존재하지 않음",
            "status": "unavailable",
        }

    if http_status == 429 or any(hint.lower() in lower_body for hint in RATE_LIMIT_HINTS):
        return {
            "detail": "속도 제한 또는 임시 차단",
            "reason": "인스타그램이 요청을 제한함",
            "status": "rate_limited",
        }

    if any(hint.lower() in lower_body for hint in PAGE_NOT_AVAILABLE_HINTS):
        return {
            "detail": "페이지를 사용할 수 없다는 문구 감지",
            "reason": "비활성화, 삭제, 이름 변경 중 하나로 추정",
            "status": "unavailable",
        }

    if "/accounts/login/" in lower_url and http_status in (301, 302, 303, 307, 308):
        return {
            "detail": "로그인 페이지로 리디렉션",
            "reason": "로그인 필요 또는 접근 제한",
            "status": "unknown",
        }

    if any(hint.lower() in lower_body for hint in LOGIN_HINTS):
        return {
            "detail": "로그인 장벽 감지",
            "reason": "로그인 없이 상태를 단정할 수 없음",
            "status": "unknown",
        }

    og_url_pattern = f'https://www.instagram.com/{normalized}/'
    og_url_pattern_www = f'https://instagram.com/{normalized}/'
    username_json_pattern = f'"username":"{normalized}"'
    alternate_name_pattern = f'"alternatename":"@{normalized}"'
    title_pattern = f"@{normalized}"

    if http_status == 200 and (
        og_url_pattern in lower_body
        or og_url_pattern_www in lower_body
        or username_json_pattern in lower_body
        or alternate_name_pattern in lower_body
        or title_pattern in lower_body
    ):
        return {
            "detail": "프로필 식별자 감지",
            "reason": "활성 계정으로 확인",
            "status": "active",
        }

    if http_status >= 500:
        return {
            "detail": f"{http_status} 서버 오류",
            "reason": "인스타그램 응답이 불안정함",
            "status": "unknown",
        }

    return {
        "detail": f"{http_status} 응답이나 명확한 프로필 단서 없음",
        "reason": "활성 여부를 단정할 수 없음",
        "status": "unknown",
    }


def fetch_profile_status(username, opener=None):
    normalized = normalize_username(username)

    if not normalized:
        return {
            "checkedAt": iso_now(),
            "detail": "빈 username",
            "httpStatus": None,
            "reason": "입력이 비어 있음",
            "status": "unknown",
            "username": username,
        }

    target_url = INSTAGRAM_WEB_PROFILE_INFO_URL.format(username=quote(normalized))
    opener = opener or build_opener()
    request = Request(
        target_url,
        headers={
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": INSTAGRAM_PROFILE_URL.format(username=quote(normalized)),
            "User-Agent": USER_AGENT,
            "X-IG-App-ID": INSTAGRAM_APP_ID,
            "X-Requested-With": "XMLHttpRequest",
        },
    )

    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            final_url = response.geturl()
            body_text = response.read().decode("utf-8", errors="replace")

            try:
                payload = json.loads(body_text)
                classification = classify_instagram_profile_payload(normalized, payload)
            except json.JSONDecodeError:
                classification = classify_instagram_profile_response(
                    normalized,
                    response.status,
                    final_url,
                    body_text,
                )

            return {
                "checkedAt": iso_now(),
                "detail": classification["detail"],
                "finalUrl": final_url,
                "httpStatus": response.status,
                "reason": classification["reason"],
                "status": classification["status"],
                "username": normalized,
            }
    except HTTPError as error:
        body_text = error.read(50000).decode("utf-8", errors="replace")

        if error.code == 404:
            classification = {
                "detail": "404 응답",
                "reason": "프로필이 존재하지 않거나 비활성화·삭제된 상태로 추정",
                "status": "unavailable",
            }
        else:
            try:
                payload = json.loads(body_text)
                classification = classify_instagram_profile_payload(normalized, payload)
            except json.JSONDecodeError:
                classification = classify_instagram_profile_response(
                    normalized,
                    error.code,
                    error.geturl(),
                    body_text,
                )

        return {
            "checkedAt": iso_now(),
            "detail": classification["detail"],
            "finalUrl": error.geturl(),
            "httpStatus": error.code,
            "reason": classification["reason"],
            "status": classification["status"],
            "username": normalized,
        }
    except URLError as error:
        return {
            "checkedAt": iso_now(),
            "detail": str(error.reason),
            "httpStatus": None,
            "reason": "네트워크 오류로 확인하지 못함",
            "status": "unknown",
            "username": normalized,
        }
    except Exception as error:  # pragma: no cover - defensive fallback
        return {
            "checkedAt": iso_now(),
            "detail": str(error),
            "httpStatus": None,
            "reason": "예상하지 못한 오류",
            "status": "unknown",
            "username": normalized,
        }


class AppRequestHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/health":
            self.respond_json({"ok": True, "checkedAt": iso_now()})
            return

        if parsed.path == "/api/profile-status":
            self.handle_profile_status(parsed.query)
            return

        if parsed.path == "/":
            self.path = "/index.html"

        super().do_GET()

    def handle_profile_status(self, query):
        params = parse_qs(query)
        usernames_param = params.get("usernames", [""])[0]
        usernames = [normalize_username(item) for item in usernames_param.split(",")]
        usernames = [item for item in usernames if item]
        usernames = list(dict.fromkeys(usernames))

        if not usernames:
            self.respond_json(
                {"error": "usernames 쿼리 파라미터가 필요합니다."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        if len(usernames) > MAX_BATCH_SIZE:
            self.respond_json(
                {"error": f"한 번에 최대 {MAX_BATCH_SIZE}개까지 확인할 수 있습니다."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        opener = build_opener()
        results = [fetch_or_get_cached_profile_status(username, opener=opener) for username in usernames]
        self.respond_json(
            {
                "checkedAt": iso_now(),
                "results": results,
            }
        )

    def respond_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_handler():
    return partial(AppRequestHandler, directory=str(ROOT_DIR))


def choose_port(preferred_port, host, allow_fallback):
    if not allow_fallback or host not in ("127.0.0.1", "localhost"):
        return preferred_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if sock.connect_ex((host, preferred_port)) != 0:
            return preferred_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def run_server(host, port):
    handler = make_handler()
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Serving on http://{host}:{port}", flush=True)
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="Serve the Instagram follow checker app locally.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--no-port-fallback", action="store_true")
    args = parser.parse_args()

    allow_fallback = not args.no_port_fallback and "PORT" not in os.environ
    port = choose_port(args.port, args.host, allow_fallback)

    try:
        run_server(args.host, port)
    except KeyboardInterrupt:
        print("\nServer stopped.", flush=True)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
