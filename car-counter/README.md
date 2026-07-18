# Traffic Intelligence Backend

Government-oriented traffic analytics on IPCamLive streams using YOLO + Supervision.

## Features

- Vehicle / pedestrian / bicycle counting
- Congestion score (vehicles/minute + queue length)
- Speed bands (slow / normal / fast) — planning-grade
- Near-miss / conflict zone events
- Heavy-truck corridor metrics
- School-zone hour reports
- Camera health (blur / dark / offline)
- Alerts (truck spike, overnight volume, camera issues)
- Incident tagging
- Before/after study snapshots
- CSV + PDF export; optional email to planners
- Public vs internal role access

## Run

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Internal demo token: `internal-demo-token` (header `X-Api-Token`).

Optional email: set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `PLANNER_EMAILS`.

## Local Video Mode

By default, the engine reads a live IPCam stream. You can switch to a downloaded video file.

Set environment variables before starting the API:

```bash
export VIDEO_SOURCE_MODE=file
export LOCAL_VIDEO_PATH="/absolute/path/to/your/video.mp4"
export LOCAL_VIDEO_LOOP=true
uvicorn main:app --reload --port 8000
```

Variables:

- `VIDEO_SOURCE_MODE`: `auto` (default), `live`, `stream`, `file`, or `local`
- `LOCAL_VIDEO_PATH`: absolute path to a local video file
- `LOCAL_VIDEO_LOOP`: `true`/`false`; when false, processing stops at end of file

Mode behavior:

- `auto`: use local file if `LOCAL_VIDEO_PATH` is set, otherwise use live stream
- `live` or `stream`: always use IPCam stream
- `file` or `local`: always use `LOCAL_VIDEO_PATH`
