"""The dashboard.

Counts, the most frequent diagnoses and the latest activity, in one glance. All the
numbers arrive pre-computed from :class:`~app.services.dashboard_service.DashboardService`;
this view counts nothing itself.
"""

from __future__ import annotations

import customtkinter as ctk

from app.domain.events import EVENT_LABELS
from app.domain.summary import DashboardSummary
from app.ui.theme import (
    FONT_BODY_BOLD,
    FONT_SMALL,
    FONT_TINY,
    GAP_MD,
    GAP_SM,
    GAP_XS,
    PALETTE,
    RADIUS_MD,
)
from app.ui.views.base import View
from app.ui.widgets.cards import EmptyState, Section, StatCard


class DashboardView(View):
    """Overview of the patient population and recent activity."""

    title = "Dashboard"
    subtitle = "An overview of the register, its diagnoses and the most recent changes."

    def build(self) -> None:
        self.content.grid_rowconfigure(1, weight=1)

        self._cards: dict[str, StatCard] = {}
        cards_row = ctk.CTkFrame(self.content, fg_color="transparent")
        cards_row.grid(row=0, column=0, sticky="ew", pady=(0, GAP_SM))
        for column in range(4):
            cards_row.grid_columnconfigure(column, weight=1, uniform="card")

        for column, (key, label) in enumerate(
            (
                ("total_patients", "Total patients"),
                ("active_patients", "Active"),
                ("active_diagnoses", "Active diagnoses"),
                ("updated_today", "Updated today"),
            )
        ):
            card = StatCard(cards_row, label=label)
            card.grid(
                row=0,
                column=column,
                sticky="nsew",
                padx=(0 if column == 0 else GAP_XS, 0),
            )
            self._cards[key] = card

        columns = ctk.CTkFrame(self.content, fg_color="transparent")
        columns.grid(row=1, column=0, sticky="nsew")
        columns.grid_columnconfigure(0, weight=1, uniform="col")
        columns.grid_columnconfigure(1, weight=1, uniform="col")
        columns.grid_rowconfigure(0, weight=1)

        self._diagnoses = Section(
            columns,
            title="Most frequent diagnoses",
            subtitle="Counted across patients currently on the register.",
        )
        self._diagnoses.grid(row=0, column=0, sticky="nsew", padx=(0, GAP_XS))

        self._activity = Section(
            columns,
            title="Recent activity",
            subtitle="The latest entries from every patient's timeline.",
            scrollable=True,
        )
        self._activity.grid(row=0, column=1, sticky="nsew", padx=(GAP_XS, 0))

        self._storage = self.caption("")
        self._storage.grid(row=2, column=0, sticky="ew", pady=(GAP_SM, 0))

    # ---------- refresh ----------

    def on_show(self) -> None:
        summary = self.container.dashboard.summary()
        self._render_cards(summary)
        self._render_diagnoses(summary)
        self._render_activity(summary)
        self._render_storage(summary)

    def _render_cards(self, summary: DashboardSummary) -> None:
        self._cards["total_patients"].set_value(
            str(summary.total_patients),
            caption=f"{summary.created_today} added today",
        )
        self._cards["active_patients"].set_value(
            str(summary.active_patients),
            caption=f"{summary.archived_patients} archived",
        )
        self._cards["active_diagnoses"].set_value(
            str(summary.active_diagnoses),
            caption="Currently being managed",
        )
        self._cards["updated_today"].set_value(
            str(summary.updated_today),
            caption=_plural(summary.updated_today, "record changed", "records changed"),
        )

    def _render_diagnoses(self, summary: DashboardSummary) -> None:
        for child in self._diagnoses.body.winfo_children():
            child.destroy()

        if not summary.has_diagnoses:
            EmptyState(
                self._diagnoses.body,
                title="No diagnoses recorded",
                message="Diagnoses appear here once they are added to a patient record.",
            ).grid(row=0, column=0, sticky="ew")
            return

        largest = max(summary.max_diagnosis_count, 1)

        for row, entry in enumerate(summary.top_diagnoses):
            line = ctk.CTkFrame(self._diagnoses.body, fg_color="transparent")
            line.grid(row=row, column=0, sticky="ew", pady=(0, GAP_SM))
            line.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                line,
                text=entry.label,
                font=FONT_SMALL,
                text_color=PALETTE.text,
                anchor="w",
            ).grid(row=0, column=0, sticky="ew")

            ctk.CTkLabel(
                line,
                text=_plural(entry.count, "patient", "patients"),
                font=FONT_TINY,
                text_color=PALETTE.text_muted,
                anchor="e",
            ).grid(row=0, column=1, sticky="e")

            # A progress bar rather than a fixed-width rectangle, so the chart
            # scales with the window instead of assuming a pixel width.
            bar = ctk.CTkProgressBar(
                line,
                height=8,
                corner_radius=4,
                progress_color=PALETTE.accent,
                fg_color=PALETTE.surface_alt,
            )
            bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(GAP_XS, 0))
            bar.set(entry.count / largest)

    def _render_activity(self, summary: DashboardSummary) -> None:
        for child in self._activity.body.winfo_children():
            child.destroy()

        if not summary.recent_events:
            EmptyState(
                self._activity.body,
                title="Nothing yet",
                message="Changes to patient records are listed here as they happen.",
            ).grid(row=0, column=0, sticky="ew")
            return

        for row, event in enumerate(summary.recent_events):
            line = ctk.CTkFrame(self._activity.body, fg_color="transparent")
            line.grid(row=row, column=0, sticky="ew", pady=(0, GAP_SM))
            line.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                line,
                text=EVENT_LABELS.get(event.event_type, event.event_type.replace("_", " ").title()),
                font=FONT_TINY,
                text_color=PALETTE.accent,
                anchor="w",
            ).grid(row=0, column=0, sticky="ew")

            ctk.CTkLabel(
                line,
                text=self.format_timestamp(event.created_at),
                font=FONT_TINY,
                text_color=PALETTE.text_muted,
                anchor="e",
            ).grid(row=0, column=1, sticky="e")

            ctk.CTkLabel(
                line,
                text=event.description or "—",
                font=FONT_SMALL,
                text_color=PALETTE.text,
                anchor="w",
                justify="left",
                wraplength=340,
            ).grid(row=1, column=0, columnspan=2, sticky="ew")

            ctk.CTkLabel(
                line,
                text=f"by {event.actor}" if event.actor else "",
                font=FONT_TINY,
                text_color=PALETTE.text_muted,
                anchor="w",
            ).grid(row=2, column=0, columnspan=2, sticky="ew")

    def _render_storage(self, summary: DashboardSummary) -> None:
        self._storage.configure(
            text=(
                f"Storage: {summary.storage_mode} · {summary.database_location} · "
                f"{_plural(summary.deleted_patients, 'deleted record', 'deleted records')} retained"
            )
        )


def _plural(count: int, singular: str, plural: str) -> str:
    """``1 patient`` / ``3 patients``, without a trailing "s" on the singular."""
    return f"{count} {singular if count == 1 else plural}"
