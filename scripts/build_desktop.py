#!/usr/bin/env python3

import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT_DIR / "dist"
ARTIFACTS_DIR = ROOT_DIR / "release"
APP_NAME = "Instagram Unfollower Checker"
APP_IDENTIFIER = "com.hawlion.instagram-unfollowers"
ENTRYPOINT = ROOT_DIR / "desktop_app.py"
DATA_FILES = [
    ROOT_DIR / "index.html",
    ROOT_DIR / "app.js",
    ROOT_DIR / "styles.css",
    ROOT_DIR / "zip-reader.js",
]


def platform_name():
    if sys.platform == "darwin":
        return "macos"

    if sys.platform.startswith("win"):
        return "windows"

    raise RuntimeError(f"지원하지 않는 빌드 플랫폼입니다: {sys.platform}")


def add_data_argument(path):
    destination_separator = ";" if sys.platform.startswith("win") else ":"
    return f"{path}{destination_separator}."


def build_command():
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--name",
        APP_NAME,
        "--collect-all",
        "webview",
    ]

    if sys.platform == "darwin":
        command.extend(["--osx-bundle-identifier", APP_IDENTIFIER])

    for path in DATA_FILES:
        command.extend(["--add-data", add_data_argument(path)])

    command.append(str(ENTRYPOINT))
    return command


def bundle_base_dir():
    if sys.platform == "darwin":
        return f"{APP_NAME}.app"

    return APP_NAME


def bundle_path():
    return DIST_DIR / bundle_base_dir()


def finalize_bundle():
    if sys.platform != "darwin":
        return

    app_bundle = bundle_path()
    subprocess.run(["xattr", "-cr", str(app_bundle)], check=True)
    subprocess.run(
        ["codesign", "--force", "--deep", "-s", "-", str(app_bundle)],
        check=True,
    )


def make_archive():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    archive_base = ARTIFACTS_DIR / f"instagram-unfollowers-{platform_name()}"
    archive_path = archive_base.with_suffix(".zip")

    if archive_path.exists():
        archive_path.unlink()

    shutil.make_archive(str(archive_base), "zip", root_dir=DIST_DIR, base_dir=bundle_base_dir())
    return archive_path


def main():
    subprocess.run(build_command(), cwd=ROOT_DIR, check=True)
    finalize_bundle()
    archive_path = make_archive()
    print(f"Created desktop archive: {archive_path}")


if __name__ == "__main__":
    main()
