"""The activity log.

The application-wide audit trail: who did what, to which record, and when. Distinct
from a patient's Timeline tab, which shows what happened to one record — this is the
view an auditor or a practice manager opens.

Entries are append-only, so this view is a pure read: it offers filtering and a
refresh, and nothing that could alter what was recorded.
"""

from __future__ import annotations

import customtkinter as ctk

from app.core.exceptions import MedFlowError
from app.domain.enums import AUDIT_ACTION_LABELS, AuditAction
from app.ui.dialogs.confirm import NotifyDialog
from app.ui.theme import (
    FONT_BODY,
    FONT_SMALL,
    FONT_TINY,
    GAP_MD,
    GAP_SM,
    GAP_XS,
    PALETTE,
    RADIUS_MD,
)
from app.ui.views.base import View
from app.ui.widgets.cards import EmptyState

PAGE_SIZE = 200

ANY_ACTION = "Any action"


class ActivityView(View):
    """Browse the audit trail."""

    title = "Activity"
    subtitle = (
        "Every change made through MedFlow, newest first. Entries are append-only "
        "and are never edited or removed."
    )

    def build(self) -> None:
        self._filter = ANY_ACTION

        self._build_actions()

        self.content.grid_rowconfigure(1, weight=1)

        controls = ctk.CTkFrame(self.content, fg_color="transparent")
        controls.grid(row=0, column=0, sticky="ew", pady=(0, GAP_XS))
        controls.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            controls, text="Action", font=FONT_TINY, text_color=PALETTE.text_muted
        ).grid(row=0, column=0, padx=(0, GAP_XS))

        self._action_menu = ctk.CTkOptionMenu(
            controls,
            values=[ANY_ACTION, *AUDIT_ACTION_LABELS.values()],
            command=self._on_filter_changed,
            width=200,
            height=30,
            font=FONT_TINY,
            dropdown_font=FONT_TINY,
            fg_color=PALETTE.surface_alt,
            button_color=PALETTE.surface_alt,
            button_hover_color=PALETTE.border,
            text_color=PALETTE.text,
        )
        self._action_menu.grid(row=0, column=1, sticky="w")
        self._action_menu.set(ANY_ACTION)

        self._summary = ctk.CTkLabel(
            controls, text="", font=FONT_TINY, text_color=PALETTE.text_muted, anchor="e"
        )
        self._summary.grid(row=0, column=2, sticky="e")

        self._panel = ctk.CTkScrollableFrame(
            self.content,
            fg_color=PALETTE.surface,
            corner_radius=RADIUS_MD,
            border_width=1,
            border_color=PALETTE.border,
        )
        self._panel.grid(row=1, column=0, sticky="nsew")
        self._panel.grid_columnconfigure(0, weight=1)

    def _build_actions(self) -> None:
        ctk.CTkButton(
            self.header_actions,
            text="Refresh",
            command=self.on_show,
            width=96,
            height=34,
            font=FONT_BODY,
            fg_color="transparent",
            border_width=1,
            border_color=PALETTE.border,
            text_color=PALETTE.text,
            hover_color=PALETTE.surface_alt,
        ).grid(row=0, column=0)

    # ---------- refresh ----------

    def on_show(self) -> None:
        try:
            entries = self.container.audit.recent(limit=PAGE_SIZE)
        except MedFlowError as error:
            NotifyDialog.show(
                self.app, title="Could not load the activity log",
                message=error.message, tone="danger",
            )
            return

        if self._filter != ANY_ACTION:
            entries = [entry for entry in entries if entry.label == self._filter]

        for child in self._panel.winfo_children():
            child.destroy()

        total = self.container.audit.count()
        self._summary.configure(
            text=f"{len(entries)} of {total} entries shown"
            + (f" · latest {PAGE_SIZE}" if total > PAGE_SIZE else "")
        )

        if not entries:
            EmptyState(
                self._panel,
                title="Nothing recorded yet",
                message="Actions taken in MedFlow are listed here as they happen.",
            ).grid(row=0, column=0, sticky="ew", pady=GAP_MD)
            return

        for row, entry in enumerate(entries):
            self._render_entry(entry, row)

    def _render_entry(self, entry, row: int) -> None:
        card = ctk.CTkFrame(
            self._panel,
            fg_color=PALETTE.surface_alt if row % 2 else "transparent",
            corner_radius=RADIUS_MD,
        )
        card.grid(row=row, column=0, sticky="ew", pady=(0, GAP_XS), padx=GAP_XS)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text=entry.label,
            font=FONT_SMALL,
            text_color=_action_colour(entry.action),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=GAP_SM, pady=(GAP_XS, 0))

        ctk.CTkLabel(
            card,
            text=self.format_timestamp(entry.created_at),
            font=FONT_TINY,
            text_color=PALETTE.text_muted,
            anchor="e",
        ).grid(row=0, column=1, sticky="e", padx=GAP_SM, pady=(GAP_XS, 0))

        ctk.CTkLabel(
            card,
            text=entry.summary,
            font=FONT_TINY,
            text_color=PALETTE.text,
            anchor="w",
            justify="left",
            wraplength=640,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", padx=GAP_SM)

        ctk.CTkLabel(
            card,
            text=f"actor: {entry.actor or 'unknown'}",
            font=FONT_TINY,
            text_color=PALETTE.text_muted,
            anchor="w",
        ).grid(row=2, column=0, columnspan=2, sticky="ew", padx=GAP_SM, pady=(0, GAP_XS))

    def _on_filter_changed(self, label: str) -> None:
        self._filter = label
        self.on_show()


def _action_colour(action: str) -> tuple[str, str]:
    if action in {AuditAction.DELETE.value, AuditAction.RESTORE_BACKUP.value}:
        return PALETTE.danger
    if action in {AuditAction.CREATE.value, AuditAction.RESTORE.value}:
        return PALETTE.success
    if action in {AuditAction.IMPORT.value, AuditAction.MIGRATE.value}:
        return PALETTE.warning
    return PALETTE.text
