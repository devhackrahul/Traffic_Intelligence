"""CSV / PDF report builders and optional email delivery."""

from __future__ import annotations

import csv
import io
import os
import smtplib
from email.message import EmailMessage
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_csv(stats: dict) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["metric", "value"])
    writer.writerow(["camera", stats.get("alias", "")])
    writer.writerow(["total_vehicles", stats.get("total", 0)])
    writer.writerow(["heavy_trucks", stats.get("heavy_trucks", 0)])
    writer.writerow(["heavy_vehicles", stats.get("heavy_vehicles", 0)])
    writer.writerow(["pedestrians", stats.get("pedestrians", 0)])
    writer.writerow(["bicycles", stats.get("by_type", {}).get("bicycle", 0)])
    writer.writerow(["congestion_score", stats.get("congestion", {}).get("score", 0)])
    writer.writerow(["vehicles_per_minute", stats.get("congestion", {}).get("vehicles_per_minute", 0)])
    writer.writerow(["queue_length", stats.get("congestion", {}).get("queue_length", 0)])
    writer.writerow([])
    writer.writerow(["class", "count"])
    for name, count in (stats.get("by_type") or {}).items():
        writer.writerow([name, count])
    writer.writerow([])
    writer.writerow(["hour", "vehicles"])
    for hour, count in sorted((stats.get("hourly") or {}).items()):
        writer.writerow([hour, count])
    writer.writerow([])
    writer.writerow(["speed_band", "count"])
    for band, count in (stats.get("speed_bands") or {}).items():
        writer.writerow([band, count])
    return buf.getvalue().encode("utf-8")


def build_pdf(stats: dict, title: str = "Traffic Analytics Report") -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(title, styles["Title"]),
        Spacer(1, 12),
        Paragraph(f"Camera: {stats.get('alias', 'n/a')}", styles["Normal"]),
        Paragraph(
            f"Peak hour: {(stats.get('peak_hour') or {}).get('label') or 'n/a'} "
            f"({(stats.get('peak_hour') or {}).get('count', 0)} vehicles)",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]

    summary = [
        ["Metric", "Value"],
        ["Total vehicles", stats.get("total", 0)],
        ["Heavy trucks", stats.get("heavy_trucks", 0)],
        ["Heavy vehicles (truck+bus)", stats.get("heavy_vehicles", 0)],
        ["Pedestrians", stats.get("pedestrians", 0)],
        ["Bicycles", (stats.get("by_type") or {}).get("bicycle", 0)],
        ["Congestion score", (stats.get("congestion") or {}).get("score", 0)],
        ["Vehicles / minute", (stats.get("congestion") or {}).get("vehicles_per_minute", 0)],
        ["Queue length", (stats.get("congestion") or {}).get("queue_length", 0)],
        ["Near-miss events", (stats.get("conflicts") or {}).get("near_miss_count", 0)],
        ["Camera health", (stats.get("camera_health") or {}).get("status", "n/a")],
    ]
    table = Table(summary, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4b5563")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 16))

    by_type = [["Class", "Count"]]
    for name, count in (stats.get("by_type") or {}).items():
        by_type.append([name, count])
    t2 = Table(by_type, hAlign="LEFT")
    t2.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#667eea")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]
        )
    )
    story.append(Paragraph("Classification totals", styles["Heading2"]))
    story.append(t2)

    doc.build(story)
    return buf.getvalue()


def email_report(
    pdf_bytes: bytes,
    subject: str,
    to_addrs: Optional[list[str]] = None,
) -> dict:
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    mail_from = os.getenv("SMTP_FROM", user)
    recipients = to_addrs or [
        a.strip()
        for a in os.getenv("PLANNER_EMAILS", "").split(",")
        if a.strip()
    ]

    if not host or not recipients:
        return {
            "sent": False,
            "reason": "Configure SMTP_HOST and PLANNER_EMAILS to enable auto-email.",
        }

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(recipients)
    msg.set_content(
        "Attached is the automated traffic analytics report from the monitoring system."
    )
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename="traffic-report.pdf",
    )

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)

    return {"sent": True, "recipients": recipients}
