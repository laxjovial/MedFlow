"""Dashboard view: the numbers that matter plus what's next."""

from __future__ import annotations

import customtkinter as ctk

from app.ui.components import EmptyState, Section, StatCard
from app.ui.theme import F_BODY, F_BOLD, F_SMALL, MUTED
from app.utils.dates import humanize, relative_label


class DashboardView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app

        ctk.CTkLabel(self, text="Today at a glance",
                     font=("Segoe UI", 22, "bold")).pack(anchor="w", padx=24,
                                                         pady=(20, 12))

        self.stats = ctk.CTkFrame(self, fg_color="transparent")
        self.stats.pack(fill="x", padx=24)
        for i in range(5):
            self.stats.grid_columnconfigure(i, weight=1)

        self.card_total = StatCard(self.stats, "Patients")
        self.card_week = StatCard(self.stats, "New this week")
        self.card_appts = StatCard(self.stats, "Appointments today")
        self.card_dx = StatCard(self.stats, "Active diagnoses")
        self.card_crit = StatCard(self.stats, "Critical labs")
        for i, card in enumerate((self.card_total, self.card_week,
                                  self.card_appts, self.card_dx,
                                  self.card_crit)):
            card.grid(row=0, column=i, sticky="ew", padx=(0, 12 if i < 4 else 0))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=24, pady=(14, 20))
        content.grid_columnconfigure((0, 1), weight=1)
        content.grid_rowconfigure(1, weight=1)

        self.next_box = Section(content, "Next appointments")
        self.next_box.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.activity_box = Section(content, "Recent activity")
        self.activity_box.grid(row=0, column=1, sticky="nsew", padx=(7, 0))

        self.next_list = ctk.CTkScrollableFrame(self.next_box, fg_color="transparent",
                                                height=180)
        self.next_list.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 10))
        self.next_box.grid_rowconfigure(1, weight=1)

        self.activity_list = ctk.CTkScrollableFrame(self.activity_box,
                                                    fg_color="transparent",
                                                    height=180)
        self.activity_list.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 10))
        self.activity_box.grid_rowconfigure(1, weight=1)

        self.quick = Section(content, "Quick actions")
        self.quick.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))

        actions = ctk.CTkFrame(self.quick, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 14))
        perms = app.permissions
        if "patients.create" in perms:
            ctk.CTkButton(actions, text="＋  Register patient", font=F_BOLD,
                          height=40, command=self._new_patient).pack(
                side="left", padx=(0, 10))
        if "appointments.manage" in perms:
            ctk.CTkButton(actions, text="🗓  Schedule appointment", font=F_BOLD,
                          height=40, fg_color="#0F766E",
                          command=self._new_appt).pack(side="left")
        if "export.data" in perms:
            ctk.CTkButton(actions, text="⤓  Export directory (CSV)", font=F_BOLD,
                          height=40, fg_color="transparent", border_width=1,
                          border_color="#DFE7F0", text_color="#16283C",
                          command=self._export_csv).pack(side="left", padx=10)

        self.refresh()

    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        stats = self.app.reports.dashboard()
        self.card_total.set(stats["total_patients"])
        self.card_week.set(stats["new_patients_7d"])
        self.card_appts.set(stats["appointments_today"])
        self.card_dx.set(stats["active_diagnoses"])
        self.card_crit.set(stats["critical_labs"],
                           alert=stats["critical_labs"] > 0)

        for w in self.next_list.winfo_children():
            w.destroy()
        appts = self.app.records.upcoming_appointments(limit=8)
        if not appts:
            EmptyState(self.next_list, "🗓", "No upcoming appointments",
                       "Scheduled visits will appear here.")
        for a in appts:
            row = ctk.CTkFrame(self.next_list, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=humanize(a["scheduled_at"]), font=F_BOLD,
                         width=130, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=f"{a['patient_name']}  ·  "
                                   f"{a.get('provider') or 'Unassigned'}",
                         font=F_BODY, anchor="w").pack(side="left", padx=8)

        for w in self.activity_list.winfo_children():
            w.destroy()
        events = self.app.audit.recent(limit=8)
        if not events:
            EmptyState(self.activity_list, "⧗", "No activity yet")
        for e in events:
            row = ctk.CTkFrame(self.activity_list, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=relative_label(e.created_at.isoformat()
                                                  if e.created_at else None),
                         font=F_SMALL, text_color=MUTED, width=70,
                         anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=f"{e.actor or 'system'} {e.action.replace('_', ' ')} "
                                   f"{e.details or ''}".strip(),
                         font=F_SMALL, anchor="w").pack(side="left", padx=6)

    def _new_patient(self) -> None:
        self.app.show_view("patients", open_new=True)

    def _new_appt(self) -> None:
        self.app.show_view("appointments", open_new=True)

    def _export_csv(self) -> None:
        self.app.export_dataset("patients")
