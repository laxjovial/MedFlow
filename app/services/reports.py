"""Reports service: dashboard metrics, trends, and report datasets.

A report is a plain dict of labels + rows so the desktop UI can render it
in a table, the API can return it as JSON, and the export engine can turn
it into CSV/PDF without translation.
"""

from __future__ import annotations

from datetime import timedelta

from app.utils.dates import to_iso, utcnow


class ReportsService:
    """Aggregate questions about the practice, answered from SQLite."""

    def __init__(self, repos):
        self.repos = repos

    def _q(self, sql: str, params: tuple = ()):
        return self.repos["patients"]._query_one(sql, params)

    def dashboard(self) -> dict:
        """The four headline numbers plus database size, one round trip."""
        today = to_iso(utcnow())[:10]
        week_ago = to_iso(utcnow() - timedelta(days=7))[:10]

        total = self._q("SELECT COUNT(*) AS c FROM patients WHERE deleted = 0")["c"]
        new_week = self._q(
            "SELECT COUNT(*) AS c FROM patients WHERE deleted = 0 "
            "AND SUBSTR(created_at, 1, 10) >= ?", (week_ago,)
        )["c"]
        active_dx = self._q(
            "SELECT COUNT(*) AS c FROM diagnoses WHERE status IN ('active', 'chronic')"
        )["c"]
        appts_today = self._q(
            "SELECT COUNT(*) AS c FROM appointments WHERE "
            "SUBSTR(scheduled_at, 1, 10) = ? AND status = 'scheduled'", (today,)
        )["c"]
        critical = self._q(
            "SELECT COUNT(*) AS c FROM lab_results WHERE flag = 'critical'"
        )["c"]
        deleted = self._q("SELECT COUNT(*) AS c FROM patients WHERE deleted = 1")["c"]

        conn = self.repos["patients"].db.connection()
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]

        return {
            "total_patients": total,
            "new_patients_7d": new_week,
            "active_diagnoses": active_dx,
            "appointments_today": appts_today,
            "critical_labs": critical,
            "deleted_patients": deleted,
            "database_bytes": page_count * page_size,
        }

    def registrations_by_week(self, weeks: int = 12) -> list[dict]:
        """Registration counts for the last N weeks, oldest first."""
        start = utcnow() - timedelta(weeks=weeks)
        rows = self.repos["patients"]._query_all(
            "SELECT SUBSTR(created_at, 1, 10) AS day, COUNT(*) AS c "
            "FROM patients WHERE deleted = 0 AND created_at >= ? "
            "GROUP BY day ORDER BY day",
            (to_iso(start),),
        )
        return [{"day": r["day"], "count": r["c"]} for r in rows]

    def top_diagnoses(self, limit: int = 10) -> list[dict]:
        rows = self.repos["diagnoses"]._query_all(
            "SELECT description, COUNT(*) AS c FROM diagnoses "
            "GROUP BY description ORDER BY c DESC LIMIT ?", (limit,)
        )
        return [{"diagnosis": r["description"], "count": r["c"]} for r in rows]

    def appointment_funnel(self, days: int = 30) -> dict:
        """Where appointments end up: scheduled through no-show."""
        cutoff = to_iso(utcnow() - timedelta(days=days))
        rows = self.repos["appointments"]._query_all(
            "SELECT status, COUNT(*) AS c FROM appointments "
            "WHERE created_at >= ? GROUP BY status", (cutoff,)
        )
        funnel = {status: 0 for status in
                  ("scheduled", "checked_in", "in_progress", "completed",
                   "cancelled", "no_show")}
        for r in rows:
            funnel[r["status"]] = r["c"]
        return funnel

    def workload_by_provider(self, days: int = 30) -> list[dict]:
        cutoff = to_iso(utcnow() - timedelta(days=days))
        rows = self.repos["appointments"]._query_all(
            "SELECT COALESCE(provider, 'Unassigned') AS provider, "
            "COUNT(*) AS appointments, "
            "SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed "
            "FROM appointments WHERE scheduled_at >= ? "
            "GROUP BY provider ORDER BY appointments DESC", (cutoff,)
        )
        return [dict(r) for r in rows]

    def dataset(self, name: str) -> dict:
        """A named report as {title, columns, rows} — export-ready."""
        if name == "patients":
            rows = self.repos["patients"]._query_all(
                "SELECT patient_number, name, age, sex, phone, diagnosis, "
                "created_at, updated_at FROM patients "
                "WHERE deleted = 0 ORDER BY patient_number"
            )
            return {
                "title": "Patient Directory",
                "columns": ["Patient No", "Name", "Age", "Sex", "Phone",
                            "Diagnosis", "Registered", "Updated"],
                "rows": [[r[c] or "" for c in
                          ("patient_number", "name", "age", "sex", "phone",
                           "diagnosis", "created_at", "updated_at")]
                         for r in rows],
            }
        if name == "appointments":
            rows = self.repos["appointments"]._query_all(
                "SELECT p.patient_number, p.name, a.scheduled_at, a.provider, "
                "a.reason, a.status FROM appointments a "
                "JOIN patients p USING (patient_id) "
                "ORDER BY a.scheduled_at DESC LIMIT 1000"
            )
            return {
                "title": "Appointments",
                "columns": ["Patient No", "Name", "When", "Provider",
                            "Reason", "Status"],
                "rows": [[r[c] or "" for c in
                          ("patient_number", "name", "scheduled_at",
                           "provider", "reason", "status")] for r in rows],
            }
        if name == "diagnoses":
            rows = self.repos["diagnoses"]._query_all(
                "SELECT p.patient_number, p.name, d.description, d.status, "
                "d.diagnosed_at, d.diagnosed_by FROM diagnoses d "
                "JOIN patients p USING (patient_id) "
                "ORDER BY d.diagnosis_id DESC LIMIT 1000"
            )
            return {
                "title": "Diagnoses",
                "columns": ["Patient No", "Name", "Diagnosis", "Status",
                            "Diagnosed At", "By"],
                "rows": [[r[c] or "" for c in
                          ("patient_number", "name", "description", "status",
                           "diagnosed_at", "diagnosed_by")] for r in rows],
            }
        if name == "medications":
            rows = self.repos["medications"]._query_all(
                "SELECT p.patient_number, p.name, m.name, m.dose, m.frequency, "
                "m.status, m.started_at FROM medications m "
                "JOIN patients p USING (patient_id) "
                "ORDER BY m.medication_id DESC LIMIT 1000"
            )
            return {
                "title": "Medications",
                "columns": ["Patient No", "Name", "Medication", "Dose",
                            "Frequency", "Status", "Started"],
                "rows": [[r[c] or "" for c in
                          ("patient_number", "name", "name", "dose",
                           "frequency", "status", "started_at")]
                         for r in rows],
            }
        if name == "audit":
            rows = self.repos["audit"]._query_all(
                "SELECT created_at, actor, action, entity_type, entity_id, "
                "details FROM audit_events ORDER BY event_id DESC LIMIT 2000"
            )
            return {
                "title": "Audit Trail",
                "columns": ["When", "Actor", "Action", "Entity", "ID", "Details"],
                "rows": [[r[c] or "" for c in
                          ("created_at", "actor", "action", "entity_type",
                           "entity_id", "details")] for r in rows],
            }
        raise ValueError(f"Unknown report '{name}'")
