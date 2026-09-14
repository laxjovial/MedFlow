"""Export service: CSV, JSON, and printable HTML.

Exports are how a small practice gets data out without a migration
project: a doctor's whole directory to CSV for a payer form, a patient's
chart to HTML for printing, or everything to JSON for a real EMR import.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.services.reports import ReportsService
from app.utils.dates import humanize, to_iso, utcnow
from app.utils.json_utils import dumps


class ExportService:
    """Produce portable artifacts from reports and patient charts."""

    def __init__(self, reports: ReportsService):
        self.reports = reports

    # ------------------------------------------------------------------ #
    # datasets -> bytes

    def dataset_csv(self, name: str) -> str:
        data = self.reports.dataset(name)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(data["columns"])
        writer.writerows(data["rows"])
        return buffer.getvalue()

    def dataset_json(self, name: str) -> str:
        data = self.reports.dataset(name)
        return dumps(data)

    def dataset_html(self, name: str) -> str:
        data = self.reports.dataset(name)
        head = "".join(f"<th>{c}</th>" for c in data["columns"])
        body = "".join(
            "<tr>" + "".join(f"<td>{_esc(v)}</td>" for v in row) + "</tr>"
            for row in data["rows"]
        )
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>MedFlow — {data['title']}</title>
<style>
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; margin: 32px; color: #1a1a2e; }}
  h1 {{ font-size: 20px; border-bottom: 2px solid #2563eb; padding-bottom: 8px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ border: 1px solid #d7dbe4; padding: 6px 10px; text-align: left; }}
  th {{ background: #f0f4ff; }}
  tr:nth-child(even) td {{ background: #fafbfe; }}
  .meta {{ color: #667; font-size: 12px; margin-top: 24px; }}
  @media print {{ body {{ margin: 12mm; }} }}
</style></head><body>
<h1>MedFlow — {data['title']}</h1>
<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
<p class="meta">Generated {utcnow_display()} by MedFlow — local medical records, on your machine.</p>
</body></html>"""

    # ------------------------------------------------------------------ #
    # single patient chart

    def patient_chart_html(self, chart: dict) -> str:
        """Printable chart summary for one patient."""
        p = chart["patient"]
        rows = [
            ("Patient Number", p.patient_number),
            ("Name", p.name),
            ("Age", p.age if p.age is not None else "—"),
            ("Sex", p.sex or "—"),
            ("Date of Birth", p.date_of_birth.isoformat() if p.date_of_birth else "—"),
            ("Phone", p.phone or "—"),
            ("Email", p.email or "—"),
            ("Address", p.address or "—"),
            ("Blood Pressure", p.blood_pressure or "—"),
            ("Heart Rate", p.heart_rate if p.heart_rate is not None else "—"),
            ("Weight", p.weight if p.weight is not None else "—"),
            ("Medical History", p.medical_history or "—"),
            ("Diagnosis", p.diagnosis or "—"),
            ("Notes", p.notes or "—"),
        ]
        detail_rows = "".join(
            f"<tr><th>{_esc(label)}</th><td>{_esc(str(value))}</td></tr>"
            for label, value in rows
        )

        def section(title: str, items: list[str]) -> str:
            if not items:
                return ""
            lis = "".join(f"<li>{_esc(i)}</li>" for i in items)
            return f"<h2>{title}</h2><ul>{lis}</ul>"

        vitals = [
            f"{_fmt_dt(v.recorded_at)} — BP {v.blood_pressure or '—'}, "
            f"HR {v.heart_rate or '—'}, Temp {v.temperature_c or '—'}°C, "
            f"SpO2 {v.oxygen_saturation or '—'}%"
            for v in chart.get("vitals", [])
        ]
        dxs = [f"{d.description} ({d.status})" for d in chart.get("diagnoses", [])]
        meds = [
            f"{m.name} {m.dose or ''} {m.frequency or ''} ({m.status})".strip()
            for m in chart.get("medications", [])
        ]
        allergies = [
            f"{a.substance} — {a.reaction or 'reaction unspecified'} ({a.severity})"
            for a in chart.get("allergies", [])
        ]
        labs = [
            f"{l.panel} · {l.analyte}: {l.value or '—'} {l.unit or ''} "
            f"[{l.flag}]".strip()
            for l in chart.get("lab_results", [])
        ]
        notes = [
            f"{_fmt_dt(n.created_at)} ({n.category}) by {n.author or '—'}: {n.body}"
            for n in chart.get("notes", [])
        ]
        appts = [
            f"{_fmt_dt(a['scheduled_at'])} — {a.get('provider') or '—'} "
            f"({a.get('status', '').replace('_', ' ')})"
            for a in chart.get("appointments", [])
        ]

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>MedFlow Chart — {_esc(p.name)}</title>
<style>
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; margin: 32px; color: #16213e; }}
  h1 {{ color: #2563eb; margin-bottom: 2px; }}
  .number {{ color: #667; margin-bottom: 18px; }}
  h2 {{ font-size: 15px; border-bottom: 1px solid #d7dbe4; padding-bottom: 4px; margin-top: 22px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 10px; }}
  th, td {{ border: 1px solid #d7dbe4; padding: 6px 10px; text-align: left; vertical-align: top; }}
  th {{ background: #f0f4ff; width: 200px; }}
  ul {{ margin: 6px 0; padding-left: 20px; font-size: 13px; }}
  .alert {{ color: #b42318; font-weight: 600; }}
  @media print {{ body {{ margin: 12mm; }} h2 {{ page-break-after: avoid; }} }}
</style></head><body>
<h1>{_esc(p.name)}</h1>
<div class="number">{_esc(p.patient_number)} · MedFlow medical record</div>
<table>{detail_rows}</table>
{section('Allergies', allergies)}
{section('Active Diagnoses', dxs)}
{section('Medications', meds)}
{section('Lab Results', labs)}
{section('Vitals History', vitals)}
{section('Appointments', appts)}
{section('Clinical Notes', notes)}
</body></html>"""

    def patient_chart_json(self, chart: dict) -> str:
        p = chart["patient"]
        payload = {
            "patient": p.to_row(),
            "vitals": [v.to_row() for v in chart.get("vitals", [])],
            "diagnoses": [d.to_row() for d in chart.get("diagnoses", [])],
            "medications": [m.to_row() for m in chart.get("medications", [])],
            "allergies": [a.to_row() for a in chart.get("allergies", [])],
            "lab_results": [l.to_row() for l in chart.get("lab_results", [])],
            "notes": [n.to_row() for n in chart.get("notes", [])],
            "timeline": [t.to_row() for t in chart.get("timeline", [])],
        }
        return dumps(payload)

    # ------------------------------------------------------------------ #
    # files

    def save(self, content: str, directory: str | Path, filename: str) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        path.write_text(content, encoding="utf-8")
        return path


def _esc(text) -> str:
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _fmt_dt(value) -> str:
    if hasattr(value, "isoformat"):
        return value.strftime("%Y-%m-%d %H:%M")
    return humanize(value)


def utcnow_display() -> str:
    return humanize(to_iso(utcnow()))
