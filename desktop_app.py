#!/usr/bin/env python3

import atexit
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

import server

try:
    import webview
except ImportError as error:  # pragma: no cover - exercised in packaged app runtime
    webview = None
    WEBVIEW_IMPORT_ERROR = error
else:
    WEBVIEW_IMPORT_ERROR = None

APP_TITLE = "Instagram Unfollower Checker"
APP_WINDOW_WIDTH = 1320
APP_WINDOW_HEIGHT = 920
APP_WINDOW_MIN_WIDTH = 960
APP_WINDOW_MIN_HEIGHT = 700
SERVER_HEALTH_PATH = "/api/health"
SERVER_STARTUP_TIMEOUT_SECONDS = 15


class DesktopServer:
    def __init__(self, host="127.0.0.1", preferred_port=8000):
        self.host = host
        self.port = server.choose_port(preferred_port, host, allow_fallback=True)
        self.httpd = server.create_app_server(host, self.port)
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="desktop-app-server", daemon=True)
        self.stopped = False
        self.url = f"http://{host}:{self.port}"

    def start(self):
        self.thread.start()
        wait_for_server(self.url + SERVER_HEALTH_PATH)

    def stop(self):
        if self.stopped:
            return

        self.stopped = True
        self.httpd.shutdown()
        self.httpd.server_close()

        if self.thread.is_alive():
            self.thread.join(timeout=5)


def wait_for_server(health_url, timeout_seconds=SERVER_STARTUP_TIMEOUT_SECONDS):
    deadline = time.time() + timeout_seconds
    last_error = None

    while time.time() < deadline:
        try:
            with urlopen(health_url, timeout=2) as response:
                if response.status == 200:
                    return
        except URLError as error:
            last_error = error
        except OSError as error:
            last_error = error

        time.sleep(0.2)

    raise RuntimeError(f"로컬 앱 서버를 시작하지 못했습니다: {last_error}")


def reveal_window(window):
    time.sleep(0.2)
    window.show()
    window.restore()

    if server.sys.platform == "darwin":
        from AppKit import NSApplication

        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)


def main():
    if webview is None:
        raise RuntimeError(f"pywebview를 불러오지 못했습니다: {WEBVIEW_IMPORT_ERROR}")

    desktop_server = DesktopServer()
    desktop_server.start()
    atexit.register(desktop_server.stop)

    window = webview.create_window(
        APP_TITLE,
        desktop_server.url,
        width=APP_WINDOW_WIDTH,
        height=APP_WINDOW_HEIGHT,
        min_size=(APP_WINDOW_MIN_WIDTH, APP_WINDOW_MIN_HEIGHT),
    )

    try:
        webview.start(reveal_window, window, debug=False)
    finally:
        desktop_server.stop()


if __name__ == "__main__":
    main()
