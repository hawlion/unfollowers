# Instagram Unfollower Checker

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2Fhawlion%2Funfollowers)

Upload an Instagram export ZIP and compare followers, following, and recently unfollowed accounts in the browser.

This app also includes a lightweight server endpoint that re-checks current unfollower candidates against Instagram's public web profile API so you can filter out accounts that look deleted or unavailable.

## Local run

```bash
python3 server.py --port 8000
```

Open `http://127.0.0.1:8000`.

## Render

This repo includes a `render.yaml` blueprint for a Python web service.

- Build command: `pip install -r requirements.txt`
- Start command: `python3 server.py --host 0.0.0.0 --port $PORT --no-port-fallback`
- Health check: `/api/health`

## Notes

- ZIP processing stays in the browser.
- The active-account recheck is heuristic and depends on Instagram's current public web responses.
