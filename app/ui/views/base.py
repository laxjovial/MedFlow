"""The base class every view extends.

Views are the only place that knows about CustomTkinter. They read from services
and render; they never touch a repository, write SQL, or decide a validation rule.

The lifecycle is deliberately small: ``build`` runs once when the view is created,
and ``on_show`` runs every time it becomes visible. Putting refresh logic in
``on_show`` rather than in the constructor is what keeps a view showing current
data without rebuilding its widgets on every navigation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from app.ui.theme import FONT_SMALL, FONT_TITLE, FONT_TINY, GAP_MD, GAP_XS, PALETTE

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from app.container import Container
    from app.ui.app import MedFlowApp


class View(ctk.CTkFrame):
    """Base class for a top-level page."""

    #: Heading shown at the top of the view.
    title: str = ""
    #: One line under the heading explaining what the view is for.
    subtitle: str = ""

    def __init__(self, master: ctk.CTkBaseClass, *, app: "MedFlowApp") -> None:
        super().__init__(master, fg_color=PALETTE.window, corner_radius=0)
        self.app = app

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=GAP_MD, pady=(GAP_MD, GAP_XS))
        header.grid_columnconfigure(0, weight=1)

        if self.title:
            ctk.CTkLabel(
                header,
                text=self.title,
                font=FONT_TITLE,
                text_color=PALETTE.text,
                anchor="w",
            ).grid(row=0, column=0, sticky="w")

        if self.subtitle:
            ctk.CTkLabel(
                header,
                text=self.subtitle,
                font=FONT_SMALL,
                text_color=PALETTE.text_muted,
                anchor="w",
                justify="left",
                wraplength=760,
            ).grid(row=1, column=0, sticky="w")

        #: Header controls, parented here by the subclass.
        self.header_actions = ctk.CTkFrame(header, fg_color="transparent")
        self.header_actions.grid(row=0, column=1, rowspan=2, sticky="e")

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew", padx=GAP_MD, pady=(0, GAP_MD))
        self.content.grid_columnconfigure(0, weight=1)

        self.build()

    # ---------- context ----------

    @property
    def container(self) -> "Container":
        """The application's services. Views reach storage only through these."""
        return self.app.container

    # ---------- lifecycle ----------

    def build(self) -> None:
        """Create the view's widgets. Called once, from the constructor."""

    def on_show(self) -> None:
        """Refresh the view. Called every time it becomes visible."""

    def on_hide(self) -> None:
        """Called when the view stops being visible."""

    # ---------- helpers ----------

    def set_status(self, message: str) -> None:
        self.app.set_status(message)

    def notify(self, title: str, message: str, *, tone: str = "info") -> None:
        self.app.notify(title, message, tone=tone)

    def confirm(self, *, title: str, message: str, detail: str = "",
                confirm_label: str = "Confirm", tone: str = "info") -> bool:
        return self.app.confirm(
            title=title, message=message, detail=detail,
            confirm_label=confirm_label, tone=tone,
        )

    def caption(self, text: str) -> ctk.CTkLabel:
        """A muted one-line caption, used for empty sections and hints."""
        return ctk.CTkLabel(
            self.content,
            text=text,
            font=FONT_TINY,
            text_color=PALETTE.text_muted,
            anchor="w",
            justify="left",
            wraplength=760,
        )

    def clear_content(self) -> None:
        """Remove everything currently in the content area."""
        for child in self.content.winfo_children():
            child.destroy()

    @staticmethod
    def format_timestamp(value: str) -> str:
        """Render a stored timestamp for display.

        Stored values are ``YYYY-MM-DD HH:MM:SS`` in UTC; the date and time are
        shown as recorded rather than reformatted, so what is displayed always
        matches what is in the database and in the audit trail.
        """
        if not value:
            return "—"
        return value.replace("T", " ")[:19]
