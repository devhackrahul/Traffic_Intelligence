"""FastAPI traffic analytics service for government monitoring."""

from __future__ import annotations

import os
import time
from typing import Generator, Literal, Optional

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from counter import CarCounterEngine
from reports import build_csv, build_pdf, email_report
from store import TrafficStore
from stream import StreamResolver

app = FastAPI(title="Traffic Analytics", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = TrafficStore()
engine = CarCounterEngine(resolver=StreamResolver(), store=store)
INTERNAL_TOKEN = os.getenv("INTERNAL_API_TOKEN", "internal-demo-token")


def _role(
    x_role: Optional[str],
    x_api_token: Optional[str],
    role_q: Optional[str],
) -> str:
    role = (x_role or role_q or "public").lower()
    if role == "internal":
        if x_api_token and x_api_token == INTERNAL_TOKEN:
            return "internal"
        # Local demo: allow internal without token when unset override
        if os.getenv("ALLOW_OPEN_INTERNAL", "true").lower() in {"1", "true", "yes"}:
            return "internal"
        raise HTTPException(status_code=401, detail="Internal access requires X-Api-Token")
    return "public"


class IncidentIn(BaseModel):
    kind: Literal["stalled_vehicle", "crash", "roadwork", "debris", "other"] = "other"
    note: str = ""


class StudyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phase: Literal["before", "after"]


class EmailIn(BaseModel):
    to: Optional[list[str]] = None
    period: Literal["daily", "weekly"] = "daily"


class SourceConfigIn(BaseModel):
    mode: Literal["auto", "live", "stream", "file", "local"]
    local_video_path: Optional[str] = None
    local_video_loop: Optional[bool] = None
    restart_if_running: bool = True


@app.get("/health")
def health() -> dict:
    stats = engine.get_stats()
    return {
        "ok": True,
        "service": "traffic-analytics",
        "camera": stats.get("camera_health", {}),
        "running": stats.get("running"),
    }


@app.get("/stats")
def stats(
    role: Optional[str] = Query(None),
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    resolved = _role(x_role, x_api_token, role)
    data = engine.public_stats() if resolved == "public" else engine.get_stats()
    data["role"] = resolved
    data["alerts"] = store.list_alerts() if resolved == "internal" else []
    return data


@app.post("/start")
def start(
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    _role(x_role, x_api_token, "internal")
    engine.start()
    return engine.get_stats()


@app.post("/stop")
def stop(
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    _role(x_role, x_api_token, "internal")
    engine.stop()
    return engine.get_stats()


@app.post("/reset")
def reset(
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    _role(x_role, x_api_token, "internal")
    engine.reset()
    return engine.get_stats()


@app.get("/source")
def get_source_config(
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    _role(x_role, x_api_token, "internal")
    config = engine.get_source_config()
    stats = engine.get_stats()
    return {
        **config,
        "running": bool(stats.get("running")),
        "input_source": stats.get("input_source"),
        "alias": stats.get("alias"),
    }


@app.post("/source")
def set_source_config(
    body: SourceConfigIn,
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    _role(x_role, x_api_token, "internal")
    was_running = engine.get_stats().get("running", False)
    if was_running and body.restart_if_running:
        engine.stop()
    config = engine.configure_source(
        mode=body.mode,
        local_video_path=body.local_video_path,
        local_video_loop=body.local_video_loop,
    )
    if was_running and body.restart_if_running:
        engine.start()
    stats = engine.get_stats()
    return {
        **config,
        "running": bool(stats.get("running")),
        "input_source": stats.get("input_source"),
        "alias": stats.get("alias"),
        "restarted": bool(was_running and body.restart_if_running),
    }


@app.get("/export/csv")
def export_csv(
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> Response:
    _role(x_role, x_api_token, "internal")
    content = build_csv(engine.get_stats())
    return Response(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=traffic-export.csv"},
    )


@app.get("/export/pdf")
def export_pdf(
    period: Literal["daily", "weekly"] = "daily",
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> Response:
    _role(x_role, x_api_token, "internal")
    title = f"{period.title()} Traffic Analytics Report"
    content = build_pdf(engine.get_stats(), title=title)
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=traffic-{period}-report.pdf"},
    )


@app.post("/export/email")
def export_email(
    body: EmailIn,
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    _role(x_role, x_api_token, "internal")
    pdf = build_pdf(engine.get_stats(), title=f"{body.period.title()} Traffic Report")
    result = email_report(pdf, subject=f"{body.period.title()} traffic report", to_addrs=body.to)
    return result


@app.get("/alerts")
def alerts(
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    _role(x_role, x_api_token, "internal")
    return {"alerts": store.list_alerts(include_acked=True)}


@app.post("/alerts/{alert_id}/ack")
def ack_alert(
    alert_id: int,
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    _role(x_role, x_api_token, "internal")
    ok = store.ack_alert(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True}


@app.get("/incidents")
def incidents(
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    _role(x_role, x_api_token, "internal")
    return {"incidents": store.list_incidents()}


@app.post("/incidents")
def create_incident(
    body: IncidentIn,
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    _role(x_role, x_api_token, "internal")
    return store.add_incident(body.kind, body.note, source="manual")


@app.post("/studies")
def create_study(
    body: StudyIn,
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    _role(x_role, x_api_token, "internal")
    return store.save_study(body.name, body.phase, engine.get_stats())


@app.get("/studies")
def list_studies(
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    _role(x_role, x_api_token, "internal")
    return {"studies": store.list_studies()}


@app.get("/studies/{name}/compare")
def compare_study(
    name: str,
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    _role(x_role, x_api_token, "internal")
    return store.compare_study(name)


@app.get("/school-zone")
def school_zone(
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    _role(x_role, x_api_token, "internal")
    stats = engine.get_stats()
    return stats.get("school_zone", {})


@app.get("/corridor")
def corridor(
    role: Optional[str] = Query(None),
    x_role: Optional[str] = Header(None),
    x_api_token: Optional[str] = Header(None),
) -> dict:
    resolved = _role(x_role, x_api_token, role)
    stats = engine.get_stats()
    freight = stats.get("freight_corridor", {})
    if resolved == "public":
        return {
            "name": freight.get("name"),
            "truck_share": freight.get("truck_share"),
            "heavy_trucks": freight.get("heavy_trucks"),
        }
    return freight


def _mjpeg_generator() -> Generator[bytes, None, None]:
    boundary = b"--frame"
    idle_frames = 0
    while True:
        jpeg = engine.get_latest_jpeg()
        if jpeg is None:
            idle_frames += 1
            if idle_frames > 300:
                break
            time.sleep(0.1)
            continue
        idle_frames = 0
        yield boundary + b"\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        time.sleep(0.03)


@app.get("/stream")
def stream() -> StreamingResponse:
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.on_event("shutdown")
def on_shutdown() -> None:
    engine.stop()
