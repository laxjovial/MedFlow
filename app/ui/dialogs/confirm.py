"""Confirmation and notification dialogs.

The standard Tk message boxes do not follow the application's appearance, so a dark
session would be interrupted by a light dialog. These are small replacements that
do — and they state the consequence of an action in the button, not just "Yes".
"""

from __future__ import annotations

from typing import Literal

import customtkinter as ctk

from app.ui.theme import (
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_HEADING,
    FONT_SMALL,
    GAP_MD,
    GAP_SM,
    PALETTE,
    RADIUS_MD,
)

Tone = Literal["info", "warning", "danger"]


class _BaseDialog(ctk.CTkToplevel):
    """Shared chrome for the small modal dialogs."""

    def __init__(self, master: ctk.CTkBaseClass, *, title: str, width: int = 420) -> None:
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.configure(fg_color=PALETTE.window)
        self.grid_columnconfigure(0, weight=1)

        self.transient(master)
        self.after(60, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
        except Exception:  # noqa: BLE001
            pass

    def _close(self) -> None:
        try:
            self.grab_release()
        except Exception:  # noqa: BLE001
            pass
        self.destroy()

    def _centre_on(self, master: ctk.CTkBaseClass) -> None:
        """Place the dialog over its parent, which reads as "about this"."""
        self.update_idletasks()
        try:
            master.update_idletasks()
            x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
            y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
            self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        except Exception:  # noqa: BLE001 - positioning is cosmetic
            pass


class ConfirmDialog(_BaseDialog):
    """A yes/no dialog. Use :meth:`ask` rather than constructing it directly."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        title: str,
        message: str,
        detail: str = "",
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
        tone: Tone = "info",
    ) -> None:
        super().__init__(master, title=title, width=460)

        self.result = False

        body = ctk.CTkFrame(
            self,
            fg_color=PALETTE.surface,
            corner_radius=RADIUS_MD,
            border_width=1,
            border_color=PALETTE.border,
        )
        body.grid(row=0, column=0, sticky="ew", padx=GAP_MD, pady=GAP_MD)
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            body,
            text=title,
            font=FONT_HEADING,
            text_color=PALETTE.text,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=GAP_SM + GAP_SM // 2, pady=(GAP_SM, 0))

        ctk.CTkLabel(
            body,
            text=message,
            font=FONT_SMALL,
            text_color=PALETTE.text_muted,
            anchor="w",
            justify="left",
            wraplength=380,
        ).grid(row=1, column=0, sticky="ew", padx=GAP_SM + GAP_SM // 2, pady=(GAP_SM, 0))

        if detail:
            ctk.CTkLabel(
                body,
                text=detail,
                font=FONT_SMALL,
                text_color=PALETTE.text,
                anchor="w",
                justify="left",
                wraplength=380,
            ).grid(row=2, column=0, sticky="ew", padx=GAP_SM + GAP_SM // 2, pady=(GAP_SM, 0))

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="e", padx=GAP_SM + GAP_SM // 2,
                     pady=(GAP_SM + GAP_SM // 2, GAP_SM + GAP_SM // 2))

        ctk.CTkButton(
            buttons,
            text=cancel_label,
            command=self._cancel,
            width=88,
            height=34,
            font=FONT_BODY,
            fg_color="transparent",
            border_width=1,
            border_color=PALETTE.border,
            text_color=PALETTE.text,
            hover_color=PALETTE.surface_alt,
        ).grid(row=0, column=0, padx=(0, GAP_SM))

        ctk.CTkButton(
            buttons,
            text=confirm_label,
            command=self._confirm,
            width=132,
            height=34,
            font=FONT_BODY_BOLD,
            fg_color=PALETTE.danger if tone == "danger" else PALETTE.accent,
            hover_color=PALETTE.danger_hover if tone == "danger" else PALETTE.accent_hover,
            text_color=PALETTE.text_inverse,
        ).grid(row=0, column=1)

        self.bind("<Escape>", lambda _event: self._cancel())
        self.bind("<Return>", lambda _event: self._confirm())

        self._centre_on(master)
        self.focus_set()

    def _confirm(self) -> None:
        self.result = True
        self._close()

    def _cancel(self) -> None:
        self.result = False
        self._close()

    @classmethod
    def ask(
        cls,
        master: ctk.CTkBaseClass,
        *,
        title: str,
        message: str,
        detail: str = "",
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
        tone: Tone = "info",
    ) -> bool:
        """Show the dialog and block until it is answered."""
        dialog = cls(
            master,
            title=title,
            message=message,
            detail=detail,
            confirm_label=confirm_label,
            cancel_label=cancel_label,
            tone=tone,
        )
        dialog.wait_window()
        return dialog.result


class NotifyDialog(_BaseDialog):
    """Tells the user something. Use :meth:`show` rather than constructing it."""

    def __init__(self, master: ctk.CTkBaseClass, *, title: str, message: str, tone: Tone = "info") -> None:
        super().__init__(master, title=title, width=440)

        accent = {
            "info": PALETTE.accent,
            "warning": PALETTE.warning,
            "danger": PALETTE.danger,
        }[tone]

        body = ctk.CTkFrame(
            self,
            fg_color=PALETTE.surface,
            corner_radius=RADIUS_MD,
            border_width=1,
            border_color=PALETTE.border,
        )
        body.grid(row=0, column=0, sticky="ew", padx=GAP_MD, pady=GAP_MD)
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            body, text=title, font=FONT_HEADING, text_color=accent, anchor="w"
        ).grid(row=0, column=0, sticky="ew", padx=GAP_SM + GAP_SM // 2, pady=(GAP_SM, 0))

        ctk.CTkLabel(
            body,
            text=message,
            font=FONT_SMALL,
            text_color=PALETTE.text_muted,
            anchor="w",
            justify="left",
            wraplength=360,
        ).grid(row=1, column=0, sticky="ew", padx=GAP_SM + GAP_SM // 2, pady=(GAP_SM, 0))

        ctk.CTkButton(
            body,
            text="Close",
            command=self._close,
            width=96,
            height=34,
            font=FONT_BODY_BOLD,
            fg_color=PALETTE.accent,
            hover_color=PALETTE.accent_hover,
            text_color=PALETTE.text_inverse,
        ).grid(row=2, column=0, sticky="e", padx=GAP_SM + GAP_SM // 2,
               pady=(GAP_SM + GAP_SM // 2, GAP_SM + GAP_SM // 2))

        self.bind("<Escape>", lambda _event: self._close())
        self.bind("<Return>", lambda _event: self._close())

        self._centre_on(master)
        self.focus_set()

    @classmethod
    def show(
        cls,
        master: ctk.CTkBaseClass,
        *,
        title: str,
        message: str,
        tone: Tone = "info",
    ) -> None:
        dialog = cls(master, title=title, message=message, tone=tone)
        dialog.wait_window()
