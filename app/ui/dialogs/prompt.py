"""A single-value prompt.

Used where the application needs one piece of text — recording a diagnosis, for
instance. Multiline is opt-in so the same dialog covers both a short value and a
free-text note without a second class.
"""

from __future__ import annotations

import customtkinter as ctk

from app.ui.dialogs.confirm import _BaseDialog
from app.ui.theme import (
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_HEADING,
    FONT_SMALL,
    FONT_TINY,
    GAP_MD,
    GAP_SM,
    GAP_XS,
    PALETTE,
    RADIUS_MD,
)


class TextPromptDialog(_BaseDialog):
    """Asks for one value. Use :meth:`ask` rather than constructing it directly."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        title: str,
        message: str = "",
        label: str = "",
        placeholder: str = "",
        initial: str = "",
        confirm_label: str = "Save",
        multiline: bool = False,
    ) -> None:
        super().__init__(master, title=title, width=480)

        #: ``None`` means the dialog was cancelled; an empty string is a submitted
        #: empty value, which the service then rejects with a readable message.
        self.value: str | None = None

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
            body, text=title, font=FONT_HEADING, text_color=PALETTE.text, anchor="w"
        ).grid(row=0, column=0, sticky="ew", padx=GAP_SM + GAP_XS, pady=(GAP_SM, 0))

        if message:
            ctk.CTkLabel(
                body,
                text=message,
                font=FONT_SMALL,
                text_color=PALETTE.text_muted,
                anchor="w",
                justify="left",
                wraplength=400,
            ).grid(row=1, column=0, sticky="ew", padx=GAP_SM + GAP_XS, pady=(GAP_XS, 0))

        if label:
            ctk.CTkLabel(
                body, text=label, font=FONT_SMALL, text_color=PALETTE.text_muted, anchor="w"
            ).grid(row=2, column=0, sticky="ew", padx=GAP_SM + GAP_XS, pady=(GAP_SM, 0))

        if multiline:
            self._input: ctk.CTkEntry | ctk.CTkTextbox = ctk.CTkTextbox(
                body, height=96, font=FONT_BODY, corner_radius=RADIUS_MD
            )
        else:
            self._input = ctk.CTkEntry(
                body,
                placeholder_text=placeholder,
                height=36,
                font=FONT_BODY,
                corner_radius=RADIUS_MD,
            )
        self._input.grid(row=3, column=0, sticky="ew", padx=GAP_SM + GAP_XS, pady=(GAP_XS, 0))

        if initial:
            if isinstance(self._input, ctk.CTkTextbox):
                self._input.insert("1.0", initial)
            else:
                self._input.insert(0, initial)

        self._error = ctk.CTkLabel(
            body, text="", font=FONT_TINY, text_color=PALETTE.danger, anchor="w"
        )
        self._error.grid(row=4, column=0, sticky="ew", padx=GAP_SM + GAP_XS)

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.grid(row=5, column=0, sticky="e", padx=GAP_SM + GAP_XS,
                     pady=(GAP_SM, GAP_SM + GAP_XS))

        ctk.CTkButton(
            buttons,
            text="Cancel",
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
            command=self._submit,
            width=132,
            height=34,
            font=FONT_BODY_BOLD,
            fg_color=PALETTE.accent,
            hover_color=PALETTE.accent_hover,
            text_color=PALETTE.text_inverse,
        ).grid(row=0, column=1)

        self.bind("<Escape>", lambda _event: self._cancel())
        self.bind("<Return>", lambda _event: self._submit())

        self._centre_on(master)
        self.after(80, self._focus_input)

    def _focus_input(self) -> None:
        try:
            self._input.focus_set()
        except Exception:  # noqa: BLE001 - focus is cosmetic
            pass

    def _submit(self) -> None:
        if isinstance(self._input, ctk.CTkTextbox):
            self.value = self._input.get("1.0", "end").strip()
        else:
            self.value = self._input.get().strip()

        if not self.value:
            # Caught here so the user keeps their place; the service enforces the
            # same rule for anything that does not come through this dialog.
            self._error.configure(text="Please enter a value.")
            return

        self._close()

    def _cancel(self) -> None:
        self.value = None
        self._close()

    @classmethod
    def ask(
        cls,
        master: ctk.CTkBaseClass,
        *,
        title: str,
        message: str = "",
        label: str = "",
        placeholder: str = "",
        initial: str = "",
        confirm_label: str = "Save",
        multiline: bool = False,
    ) -> str | None:
        """Show the dialog and return the submitted value, or ``None`` if cancelled."""
        dialog = cls(
            master,
            title=title,
            message=message,
            label=label,
            placeholder=placeholder,
            initial=initial,
            confirm_label=confirm_label,
            multiline=multiline,
        )
        dialog.wait_window()
        return dialog.value
