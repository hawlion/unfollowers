#!/usr/bin/env python3

import atexit
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from threading import Thread
from urllib.error import URLError
from urllib.request import urlopen

import server

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
SERVER_HEALTH_PATH = "/api/health"
SERVER_STARTUP_TIMEOUT_SECONDS = 15
SERVER_IDLE_TIMEOUT_SECONDS = 30 * 60


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


def is_server_healthy(base_url):
    try:
        wait_for_server(base_url + SERVER_HEALTH_PATH, timeout_seconds=1.5)
        return True
    except RuntimeError:
        return False


def open_url(url):
    if sys.platform == "darwin":
        subprocess.run(["open", url], check=False)
        return

    if sys.platform.startswith("win"):
        os.startfile(url)
        return

    webbrowser.open(url, new=1)


def show_error(message):
    if sys.platform == "darwin":
        escaped = message.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display alert "Instagram Unfollower Checker" message "{escaped}" as critical',
            ],
            check=False,
        )
        return

    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "Instagram Unfollower Checker", 0x10)
            return
        except Exception:
            pass

    print(message, file=sys.stderr, flush=True)


class DesktopServer:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, idle_timeout_seconds=SERVER_IDLE_TIMEOUT_SECONDS):
        self.host = host
        self.port = port
        self.idle_timeout_seconds = idle_timeout_seconds
        self.httpd = server.create_app_server(
            host,
            port,
            inactivity_timeout_seconds=idle_timeout_seconds,
        )
        self.thread = Thread(target=self.httpd.serve_forever, name="desktop-app-server", daemon=False)
        self.monitor_thread = None
        self.stopped = False
        self.url = f"http://{host}:{port}"

    def start(self):
        self.thread.start()
        self.monitor_thread = server.start_idle_shutdown_monitor(self.httpd)
        wait_for_server(self.url + SERVER_HEALTH_PATH)

    def stop(self):
        if self.stopped:
            return

        self.stopped = True
        self.httpd.shutdown()
        self.httpd.server_close()

        if self.thread.is_alive():
            self.thread.join(timeout=5)

    def wait(self):
        self.thread.join()


def start_or_open_existing(host=DEFAULT_HOST, port=DEFAULT_PORT):
    base_url = f"http://{host}:{port}"

    if is_server_healthy(base_url):
        open_url(base_url)
        return 0

    desktop_server = DesktopServer(host=host, port=port)
    desktop_server.start()
    atexit.register(desktop_server.stop)
    open_url(desktop_server.url)
    desktop_server.wait()
    return 0


def main():
    try:
        return start_or_open_existing()
    except OSError as error:
        if getattr(error, "errno", None) == 48:
            show_error(
                "127.0.0.1:8000 포트를 다른 앱이 사용 중입니다. 해당 앱을 종료한 뒤 다시 실행해 주세요."
            )
            return 1

        show_error(str(error))
        return 1
    except Exception as error:
        show_error(str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main())
