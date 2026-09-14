"""Activity view: the operational audit trail."""

from __future__ import annotations

import customtkinter as ctk

from app.ui.components import EmptyState, Section, Toolbar
from app.ui.theme import F_BODY, F_BOLD, F_SMALL, MUTED
from app.utils.dates import humanize


class ActivityView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.query = ""

        self.toolbar = Toolbar(self, "Filter by actor, action or details…",
                               on_search=self._on_search)
        self.toolbar.pack(fill="x", padx=24, pady=(20, 10))

        self.card = Section(self, "Audit trail")
        self.card.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        self.rows = ctk.CTkScrollableFrame(self.card, fg_color="transparent")
        self.rows.grid(row=1, column=0, sticky="nsew", padx=8, pady=(2, 10))
        self.card.grid_rowconfigure(1, weight=1)

        self.refresh()

    def _on_search(self, query: str) -> None:
        self.query = (query or "").lower()
        self.refresh()

    def refresh(self) -> None:
        for w in self.rows.winfo_children():
            w.destroy()
        events = self.app.audit.recent(limit=400)
        if self.query:
            events = [e for e in events if self.query in (
                f"{e.actor} {e.action} {e.entity_type} {e.entity_id} "
                f"{e.details or ''}").lower()]
        if not events:
            EmptyState(self.rows, "⧗", "No activity recorded yet",
                       "Every sign-in and change is logged here.")
            return
        for e in events:
            row = ctk.CTkFrame(self.rows, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=humanize(e.created_at.isoformat()
                                            if e.created_at else None),
                         font=F_SMALL, text_color=MUTED, width=130,
                         anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=f"{e.actor or 'system':<14}", font=F_BOLD,
                         width=130, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=f"{e.action}  {e.entity_type} "
                                   f"{e.entity_id or ''}  {e.details or ''}",
                         font=F_BODY, anchor="w").pack(side="left", padx=6)
