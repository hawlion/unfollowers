# Instagram Unfollower Checker

Upload an Instagram export ZIP and compare followers, following, and recently unfollowed accounts in the browser.

This app also includes a lightweight server endpoint that re-checks current unfollower candidates against Instagram's public web profile API so you can filter out accounts that look deleted or unavailable.

## Local run

```bash
python3 server.py --port 8000
```

Open `http://127.0.0.1:8000`.

## Desktop app build

This repo can also be packaged as a desktop app for macOS and Windows.

Install desktop build dependencies:

```bash
python3 -m pip install -r requirements.txt -r requirements-desktop.txt
```

Build the desktop package for the current OS:

```bash
python3 scripts/build_desktop.py
```

Build output:

- Shareable archive: `release/instagram-unfollowers-<platform>.zip`
- macOS installer image: `release/instagram-unfollowers-macos.dmg`

## GitHub Actions desktop builds

The repo includes `.github/workflows/build-desktop.yml`.

- Run it from the Actions tab with `workflow_dispatch`, or
- push a tag matching `desktop-v*`

Artifacts are uploaded as zipped desktop builds for macOS and Windows.

## Render

This repo includes a `render.yaml` blueprint for a Python web service.

- Build command: `pip install -r requirements.txt`
- Start command: `python3 server.py --host 0.0.0.0 --port $PORT --no-port-fallback`
- Health check: `/api/health`

## Notes

- ZIP processing stays in the browser.
- The active-account recheck is heuristic and depends on Instagram's current public web responses.
- Desktop builds on both macOS and Windows launch the same local server in the background and open the app in your default browser.
- Background desktop servers stop automatically after a period of inactivity.
- On macOS, prefer the `.dmg` and move the app to `Applications` before launching.
