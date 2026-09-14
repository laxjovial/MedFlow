"""Appointments view: the day's schedule plus scheduling dialog."""

from __future__ import annotations

import customtkinter as ctk

from app.ui.components import EmptyState, FormDialog, FormField, Section
from app.ui.theme import DANGER, F_BOLD, F_SMALL, MUTED
from app.utils.dates import humanize


class AppointmentsView(ctk.CTkFrame):
    def __init__(self, master, app, open_new: bool = False):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.scope = "upcoming"

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(20, 10))
        self._scope_var = ctk.StringVar(value="Upcoming")
        seg = ctk.CTkSegmentedControl(
            top, values=["Today", "Upcoming"],
            command=self._switch_scope, height=34)
        seg.set("Upcoming")
        seg.pack(side="left")
        if "appointments.manage" in app.permissions:
            ctk.CTkButton(top, text="＋  Schedule", font=F_BOLD, height=38,
                          command=self._schedule).pack(side="right")

        self.list_card = Section(self, "Appointments")
        self.list_card.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        self.rows = ctk.CTkScrollableFrame(self.list_card, fg_color="transparent")
        self.rows.grid(row=1, column=0, sticky="nsew", padx=8, pady=(2, 10))
        self.list_card.grid_rowconfigure(1, weight=1)

        self.refresh()
        if open_new:
            self.after(120, self._schedule)

    def _switch_scope(self, value: str) -> None:
        self.scope = "today" if value == "Today" else "upcoming"
        self.refresh()

    def refresh(self) -> None:
        for w in self.rows.winfo_children():
            w.destroy()
        appts = (self.app.records.todays_schedule() if self.scope == "today"
                 else self.app.records.upcoming_appointments(limit=100))
        if not appts:
            EmptyState(self.rows, "🗓", "Nothing scheduled",
                       "Upcoming appointments will appear here.")
            return

        for a in appts:
            row = ctk.CTkFrame(self.rows, fg_color="#FFFFFF",
                               corner_radius=9, border_width=1,
                               border_color="#DFE7F0")
            row.pack(fill="x", pady=3)
            body = ctk.CTkFrame(row, fg_color="transparent")
            body.pack(side="left", fill="x", expand=True, padx=12, pady=8)
            ctk.CTkLabel(body, text=f"{humanize(a['scheduled_at'])}  —  "
                                    f"{a['patient_name']}",
                         font=F_BOLD, anchor="w").pack(fill="x")
            ctk.CTkLabel(body, text=f"{a.get('provider') or 'Unassigned'}"
                                    f"{('  ·  ' + a['reason']) if a.get('reason') else ''}"
                                    f"  ·  {a['status'].replace('_', ' ')}",
                         font=F_SMALL, text_color=MUTED,
                         anchor="w").pack(fill="x")

            if "appointments.manage" in self.app.permissions:
                actions = ctk.CTkFrame(row, fg_color="transparent")
                actions.pack(side="right", padx=10)
                next_status = {"scheduled": "checked_in",
                               "checked_in": "in_progress",
                               "in_progress": "completed"}.get(a["status"])
                if next_status:
                    ctk.CTkButton(actions, text="→ " + next_status.replace("_", " "),
                                  font=F_SMALL, height=30,
                                  command=lambda i=a["appointment_id"],
                                          s=next_status: self._advance(i, s)
                                  ).pack(side="left", padx=3)
                if a["status"] in ("scheduled", "checked_in"):
                    ctk.CTkButton(actions, text="No-show", font=F_SMALL, height=30,
                                  fg_color="#FDECEA", hover_color="#F8D7D4",
                                  text_color=DANGER,
                                  command=lambda i=a["appointment_id"]:
                                  self._set_status(i, "no_show")).pack(side="left")

    def _advance(self, appointment_id: int, status: str) -> None:
        self._set_status(appointment_id, status)

    def _set_status(self, appointment_id: int, status: str) -> None:
        try:
            self.app.records.set_appointment_status(appointment_id, status)
            self.app.toast(f"Appointment {status.replace('_', ' ')}", "ok")
        except Exception as exc:
            self.app.toast(str(exc), "error")
        self.refresh()

    def _schedule(self) -> None:
        fields = [
            FormField("patient_number", "Patient number", required=True,
                      placeholder="e.g. MF-000012"),
            FormField("scheduled_at", "When", required=True,
                      placeholder="YYYY-MM-DD HH:MM"),
            FormField("provider", "Provider"),
            FormField("reason", "Reason"),
        ]
        FormDialog(self, "Schedule appointment", fields, self._submit,
                   submit_text="Schedule")

    def _submit(self, values: dict) -> None:
        patient = self.app.patients.get_by_number(values["patient_number"])
        when = (values["scheduled_at"] or "").replace(" ", "T").strip()
        self.app.records.schedule_appointment(
            patient.patient_id, when,
            provider=values.get("provider"), reason=values.get("reason"))
        self.app.toast("Appointment scheduled", "ok")
        self.refresh()
