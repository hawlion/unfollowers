#!/usr/bin/env python3

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT_DIR / "release"
BUILD_ROOT_DIR = Path(tempfile.gettempdir()) / "instagram-unfollowers-desktop-build"
DIST_DIR = BUILD_ROOT_DIR / "dist"
WORK_DIR = BUILD_ROOT_DIR / "build"
SPEC_DIR = BUILD_ROOT_DIR / "spec"
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
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(WORK_DIR),
        "--specpath",
        str(SPEC_DIR),
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


def make_macos_dmg():
    if sys.platform != "darwin":
        return None

    staging_dir = BUILD_ROOT_DIR / "dmg-staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)

    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_app = staging_dir / bundle_base_dir()
    subprocess.run(["ditto", str(bundle_path()), str(staged_app)], check=True)

    applications_link = staging_dir / "Applications"
    if applications_link.exists() or applications_link.is_symlink():
        applications_link.unlink()

    applications_link.symlink_to("/Applications")

    dmg_path = ARTIFACTS_DIR / "instagram-unfollowers-macos.dmg"
    if dmg_path.exists():
        dmg_path.unlink()

    subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            APP_NAME,
            "-srcfolder",
            str(staging_dir),
            "-ov",
            "-format",
            "UDZO",
            str(dmg_path),
        ],
        check=True,
    )
    return dmg_path


def main():
    if BUILD_ROOT_DIR.exists():
        shutil.rmtree(BUILD_ROOT_DIR)

    subprocess.run(build_command(), cwd=ROOT_DIR, check=True)
    finalize_bundle()
    archive_path = make_archive()
    dmg_path = make_macos_dmg()
    print(f"Created desktop archive: {archive_path}")
    if dmg_path is not None:
        print(f"Created macOS disk image: {dmg_path}")


if __name__ == "__main__":
    main()
