"""Reports view: trend summaries with export actions."""

from __future__ import annotations

import customtkinter as ctk

from app.ui.components import Section
from app.ui.theme import F_BODY, F_SMALL, MUTED

REPORTS = (
    ("patients", "Patient directory"),
    ("appointments", "Appointments"),
    ("diagnoses", "Diagnoses"),
    ("medications", "Medications"),
    ("audit", "Audit trail"),
)


class ReportsView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app

        ctk.CTkLabel(self, text="Reports & exports",
                     font=("Segoe UI", 22, "bold")).pack(anchor="w", padx=24,
                                                         pady=(20, 4))
        ctk.CTkLabel(self, text="Trends update live from the database; "
                                "exports are portable files on your disk.",
                     font=F_SMALL, text_color=MUTED).pack(anchor="w", padx=24)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(12, 20))
        body.grid_columnconfigure((0, 1), weight=1)
        body.grid_rowconfigure(1, weight=1)

        top_dx = Section(body, "Top diagnoses")
        top_dx.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        top_prov = Section(body, "Provider workload (30 days)")
        top_prov.grid(row=0, column=1, sticky="nsew", padx=(7, 0))

        self.dx_list = ctk.CTkScrollableFrame(top_dx, fg_color="transparent",
                                              height=150)
        self.dx_list.grid(row=1, column=0, sticky="nsew", padx=8, pady=(2, 10))
        self.prov_list = ctk.CTkScrollableFrame(top_prov, fg_color="transparent",
                                                height=150)
        self.prov_list.grid(row=1, column=0, sticky="nsew", padx=8, pady=(2, 10))

        exports = Section(body, "Export datasets")
        exports.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(14, 0))
        row = ctk.CTkFrame(exports, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 14))
        for name, label in REPORTS:
            ctk.CTkButton(row, text=f"{label} → CSV", font=F_SMALL, height=34,
                          fg_color="transparent", border_width=1,
                          border_color="#DFE7F0", text_color="#16283C",
                          command=lambda n=name: self.app.export_dataset(n)
                          ).pack(side="left", padx=(0, 8), pady=4)

        self.refresh()

    def refresh(self) -> None:
        for w in self.dx_list.winfo_children():
            w.destroy()
        for row in self.app.reports.top_diagnoses(limit=8):
            ctk.CTkLabel(self.dx_list,
                         text=f"{row['count']}×  {row['diagnosis'] or 'Unspecified'}",
                         font=F_BODY, anchor="w").pack(fill="x", pady=2)

        for w in self.prov_list.winfo_children():
            w.destroy()
        workload = self.app.reports.workload_by_provider(days=30)
        if not workload:
            ctk.CTkLabel(self.prov_list, text="No appointments yet",
                         font=F_SMALL, text_color=MUTED,
                         anchor="w").pack(fill="x", pady=2)
        for row in workload:
            ctk.CTkLabel(self.prov_list,
                         text=f"{row['appointments']} appts · {row['completed']} done — "
                              f"{row['provider']}",
                         font=F_BODY, anchor="w").pack(fill="x", pady=2)
