"""Reusable presentation widgets.

Small, self-contained, and free of application state: each one is told what to
show and knows nothing about patients, services or the database. That keeps them
testable at import level and reusable across views.
"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from app.ui.theme import (
    FONT_BODY_BOLD,
    FONT_METRIC,
    FONT_SMALL,
    FONT_TINY,
    GAP_SM,
    GAP_XS,
    PALETTE,
    RADIUS_MD,
)


class StatCard(ctk.CTkFrame):
    """A single metric: a label, a large value and an optional caption."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        label: str,
        value: str = "0",
        caption: str = "",
        accent: tuple[str, str] | None = None,
    ) -> None:
        super().__init__(
            master,
            fg_color=PALETTE.surface,
            corner_radius=RADIUS_MD,
            border_width=1,
            border_color=PALETTE.border,
        )

        self.grid_columnconfigure(0, weight=1)

        self._label = ctk.CTkLabel(
            self,
            text=label.upper(),
            font=FONT_TINY,
            text_color=PALETTE.text_muted,
            anchor="w",
        )
        self._label.grid(row=0, column=0, sticky="ew", padx=GAP_SM + GAP_XS, pady=(GAP_SM + GAP_XS, 0))

        self._value = ctk.CTkLabel(
            self,
            text=value,
            font=FONT_METRIC,
            text_color=accent or PALETTE.text,
            anchor="w",
        )
        self._value.grid(row=1, column=0, sticky="ew", padx=GAP_SM + GAP_XS, pady=(0, 0))

        self._caption = ctk.CTkLabel(
            self,
            text=caption,
            font=FONT_TINY,
            text_color=PALETTE.text_muted,
            anchor="w",
        )
        self._caption.grid(
            row=2, column=0, sticky="ew", padx=GAP_SM + GAP_XS, pady=(0, GAP_SM + GAP_XS)
        )

    def set_value(self, value: str, *, caption: str | None = None) -> None:
        """Update the displayed metric without rebuilding the card."""
        self._value.configure(text=value)
        if caption is not None:
            self._caption.configure(text=caption)


class Section(ctk.CTkFrame):
    """A titled block of content, used to group related fields on a view."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        title: str,
        subtitle: str = "",
        scrollable: bool = False,
    ) -> None:
        super().__init__(
            master,
            fg_color=PALETTE.surface,
            corner_radius=RADIUS_MD,
            border_width=1,
            border_color=PALETTE.border,
        )

        self.grid_columnconfigure(0, weight=1)
        header_height = GAP_SM + GAP_XS

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=GAP_SM + GAP_XS, pady=(header_height, 0))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text=title, font=FONT_BODY_BOLD, text_color=PALETTE.text, anchor="w"
        ).grid(row=0, column=0, sticky="ew")

        #: Header controls are parented here by the caller: Tk widgets cannot be
        #: reparented after creation, so the container has to be public.
        self.actions = ctk.CTkFrame(header, fg_color="transparent")
        self.actions.grid(row=0, column=1, sticky="e")

        if subtitle:
            ctk.CTkLabel(
                self,
                text=subtitle,
                font=FONT_TINY,
                text_color=PALETTE.text_muted,
                anchor="w",
                justify="left",
                wraplength=520,
            ).grid(row=1, column=0, sticky="ew", padx=GAP_SM + GAP_XS, pady=(0, GAP_XS))

        if scrollable:
            self.body: ctk.CTkBaseClass = ctk.CTkScrollableFrame(self, fg_color="transparent")
        else:
            self.body = ctk.CTkFrame(self, fg_color="transparent")

        self.body.grid(row=2, column=0, sticky="nsew", padx=GAP_SM, pady=(GAP_XS, GAP_SM))
        self.body.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)


class FieldRow(ctk.CTkFrame):
    """A read-only label/value pair, used on the patient profile."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        label: str,
        value: str = "",
        wraplength: int = 320,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self,
            text=label,
            font=FONT_SMALL,
            text_color=PALETTE.text_muted,
            anchor="w",
            width=132,
        ).grid(row=0, column=0, sticky="nw", pady=GAP_XS)

        self._value = ctk.CTkLabel(
            self,
            text=value or "—",
            font=FONT_SMALL,
            text_color=PALETTE.text,
            anchor="w",
            justify="left",
            wraplength=wraplength,
        )
        self._value.grid(row=0, column=1, sticky="ew", pady=GAP_XS)

    def set_value(self, value: str) -> None:
        self._value.configure(text=value or "—")


class EmptyState(ctk.CTkFrame):
    """Shown in place of content that does not exist yet.

    An empty panel with no explanation reads as a bug; saying what is missing and
    offering the action that fixes it does not.
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        title: str,
        message: str = "",
        action_label: str = "",
        command: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text=title, font=FONT_BODY_BOLD, text_color=PALETTE.text
        ).grid(row=0, column=0, pady=(GAP_LG, GAP_XS))

        if message:
            ctk.CTkLabel(
                self,
                text=message,
                font=FONT_SMALL,
                text_color=PALETTE.text_muted,
                wraplength=420,
                justify="center",
            ).grid(row=1, column=0, pady=(0, GAP_SM))

        if action_label and command is not None:
            ctk.CTkButton(
                self,
                text=action_label,
                command=command,
                font=FONT_BODY_BOLD,
                fg_color=PALETTE.accent,
                hover_color=PALETTE.accent_hover,
                height=34,
            ).grid(row=2, column=0, pady=(0, GAP_LG))
