# Traffic Intelligence

> Open-source live traffic analytics for cities and planners — count vehicles at intersections, measure congestion, track freight and school-zone activity, and export reports from existing street cameras.

Built with **YOLO + Roboflow Supervision** and a **Next.js** dashboard. Designed to help local government turn public camera feeds into actionable transportation data.

## Why this exists

Transportation teams need continuous traffic data without expensive temporary counters. This project turns an IP camera stream into:

- Intersection vehicle counts (through traffic + side-street turns)
- Congestion score (vehicles/minute + queue length)
- Vehicle mix (cars, trucks, buses, motorcycles, bikes, pedestrians)
- Heavy-truck / freight corridor metrics
- School-zone hour volumes
- Safety conflict (near-miss) monitoring
- CSV / PDF exports for studies and grant applications

## Quick start

### Backend

```bash
cd car-counter
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd "Potholes detection using satellite road data"
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) — use **Internal** mode to start a session.

## Features

- Intersection zone counting (not a single tripwire — works for junctions)
- Congestion score and queue estimates
- Speed bands: slow / normal / fast (planning-grade)
- Pedestrian & bicycle counts
- Alerts: truck spike, overnight volume, camera offline/blur
- Near-miss conflict zone over crosswalks
- Before/after study snapshots
- School-zone hour reports
- Incident tagging
- Camera health monitor
- Public vs internal access roles
- CSV + daily/weekly PDF export; optional planner email

## Stack

- Python FastAPI + Ultralytics YOLO + Supervision
- Next.js / TypeScript dashboard
- Optional SQLite persistence for events, alerts, and studies

## Sharing

If this is useful for your city, agency, or class project, star the repo and share it:

## License

Use freely for research, civic tech, and planning demos. Adapt to your cameras and local workflows.
