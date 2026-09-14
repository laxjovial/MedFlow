"""Reusable CustomTkinter building blocks shared by every view."""

from __future__ import annotations

import customtkinter as ctk
from tkinter import filedialog

from app.ui.theme import (
    ACCENT, ACCENT_DARK, ACCENT_SOFT, DANGER, F_BODY, F_BOLD, F_H2, F_H3,
    F_SMALL, F_STAT, INK, LINE, MUTED, OK,
)

__all__ = ["StatCard", "Section", "EmptyState", "Toolbar", "FormField",
           "FormDialog", "Toast", "pick_file"]


class StatCard(ctk.CTkFrame):
    """One dashboard number with a caption."""

    def __init__(self, master, title: str, value: str = "–", alert: bool = False):
        super().__init__(master, corner_radius=12,
                         border_width=1, border_color=LINE)
        self.grid_columnconfigure(0, weight=1)
        self._num = ctk.CTkLabel(self, text=str(value), font=F_STAT,
                                 text_color=DANGER if alert else ACCENT)
        self._num.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 0))
        self._cap = ctk.CTkLabel(self, text=title, font=F_SMALL, text_color=MUTED)
        self._cap.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))

    def set(self, value, alert: bool | None = None) -> None:
        self._num.configure(text=str(value))
        if alert is not None:
            self._num.configure(text_color=DANGER if alert else ACCENT)


class Section(ctk.CTkFrame):
    """A titled card used across views."""

    def __init__(self, master, title: str):
        super().__init__(master, corner_radius=12, border_width=1,
                         border_color=LINE)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=title.upper(), font=F_H3, text_color=MUTED,
                     anchor="w").grid(row=0, column=0, sticky="ew",
                                      padx=16, pady=(12, 4))


class EmptyState(ctk.CTkFrame):
    """Friendly placeholder when a list or view has nothing to show."""

    def __init__(self, master, icon: str, title: str, subtitle: str = ""):
        super().__init__(master, fg_color="transparent")
        self.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(self, text=icon, font=("Segoe UI", 40)).grid(
            row=0, column=0, pady=(24, 4))
        ctk.CTkLabel(self, text=title, font=F_BOLD).grid(row=1, column=0)
        if subtitle:
            ctk.CTkLabel(self, text=subtitle, font=F_SMALL,
                         text_color=MUTED).grid(row=2, column=0, pady=(2, 24))


class Toolbar(ctk.CTkFrame):
    """Search box + primary action row."""

    def __init__(self, master, placeholder: str,
                 on_search=None, button_text: str | None = None,
                 on_button=None):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self._search_var = ctk.StringVar()
        entry = ctk.CTkEntry(self, placeholder_text=placeholder,
                             textvariable=self._search_var,
                             font=F_BODY, height=38)
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        entry.bind("<KeyRelease>", self._debounced(on_search))
        self._button = None
        if button_text:
            self._button = ctk.CTkButton(
                self, text=button_text, font=F_BOLD, height=38,
                fg_color=ACCENT, hover_color=ACCENT_DARK,
                command=on_button)
            self._button.grid(row=0, column=1)

    def _debounced(self, callback):
        if callback is None:
            return lambda _e: None
        job = {"id": None}

        def handler(_event=None):
            if job["id"]:
                self.after_cancel(job["id"])
            job["id"] = self.after(220, lambda: callback(self._search_var.get()))
        return handler

    def set_button_visible(self, visible: bool) -> None:
        if self._button:
            self._button.grid() if visible else self._button.grid_remove()


class FormField:
    """Declarative field spec for :class:`FormDialog`."""

    def __init__(self, key: str, label: str, kind: str = "entry",
                 required: bool = False, options: tuple = (),
                 width: int = 260, rows: int = 3, placeholder: str = ""):
        self.key, self.label, self.kind = key, label, kind
        self.required, self.options = required, options
        self.width, self.rows, self.placeholder = width, rows, placeholder


class FormDialog(ctk.CTkToplevel):
    """Modal record form driven by a list of :class:`FormField` specs.

    On save it calls ``on_submit(values: dict)``; service ValidationError
    messages are rendered field by field, and the dialog stays open.
    """

    def __init__(self, master, title: str, fields: list[FormField],
                 on_submit, values: dict | None = None,
                 submit_text: str = "Save"):
        super().__init__(master)
        self.title(title)
        self.geometry("560x640")
        self.resizable(False, True)
        self.transient(master)
        self.after(80, self.grab_set)      # safe modal grab
        self.fields = fields
        self.on_submit = on_submit
        self.widgets: dict[str, ctk.CTkBaseClass] = {}

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(18, 6))
        ctk.CTkLabel(header, text=title, font=F_H2).pack(side="left")

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=8)

        values = values or {}
        for spec in fields:
            self._build_field(body, spec, values.get(spec.key))

        self.error = ctk.CTkLabel(self, text="", font=F_SMALL, text_color=DANGER,
                                  wraplength=500, justify="left")
        self.error.pack(fill="x", padx=20)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=20, pady=(4, 18))
        ctk.CTkButton(footer, text="Cancel", font=F_BODY, height=38,
                      fg_color="transparent", border_width=1,
                      border_color=LINE, text_color=INK,
                      command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(footer, text=submit_text, font=F_BOLD, height=38,
                      fg_color=ACCENT, hover_color=ACCENT_DARK,
                      command=self._save).pack(side="right")

    # ------------------------------------------------------------------ #

    def _build_field(self, parent, spec: FormField, value):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=(10, 0))
        label = f"{spec.label}" + (" *" if spec.required else "")
        ctk.CTkLabel(frame, text=label, font=F_SMALL, text_color=MUTED,
                     anchor="w").pack(fill="x")
        if spec.kind == "textbox":
            widget = ctk.CTkTextbox(frame, height=spec.rows * 22, font=F_BODY)
            widget.insert("1.0", str(value or ""))
            widget.pack(fill="x", pady=(3, 0))
            self.widgets[spec.key] = widget
        elif spec.kind == "option":
            widget = ctk.CTkOptionMenu(frame, values=list(spec.options) or ["—"],
                                       font=F_BODY, height=36,
                                       fg_color=ACCENT_SOFT,
                                       button_color=ACCENT,
                                       button_hover_color=ACCENT_DARK,
                                       text_color=INK)
            widget.set(str(value) if value else (spec.options[0] if spec.options else "—"))
            widget.pack(fill="x", pady=(3, 0))
            self.widgets[spec.key] = widget
        else:
            widget = ctk.CTkEntry(frame, font=F_BODY, height=36,
                                  placeholder_text=spec.placeholder)
            if value:
                widget.insert(0, str(value))
            widget.pack(fill="x", pady=(3, 0))
            self.widgets[spec.key] = widget

    def _collect(self) -> dict:
        out = {}
        for spec in self.fields:
            w = self.widgets[spec.key]
            if spec.kind == "textbox":
                out[spec.key] = w.get("1.0", "end").strip()
            elif spec.kind == "option":
                out[spec.key] = w.get()
            else:
                out[spec.key] = w.get().strip()
            if out[spec.key] in ("", "—"):
                out[spec.key] = None
        return out

    def _save(self):
        values = self._collect()
        try:
            self.on_submit(values)
        except Exception as exc:                    # service ValidationError et al.
            messages = getattr(exc, "errors", None)
            text = ("; ".join(f"{k}: {', '.join(v)}" for k, v in messages.items())
                    if isinstance(messages, dict) else str(exc))
            self.error.configure(text=text)
            return
        self.destroy()


class Toast:
    """Bottom-center transient notification."""

    _current = None

    def __init__(self, master, message: str, kind: str = "info"):
        if Toast._current is not None:
            try:
                Toast._current.destroy()
            except Exception:
                pass
        colors = {"info": (INK, "#FFFFFF"), "ok": (OK, "#FFFFFF"),
                  "error": (DANGER, "#FFFFFF")}
        fg = colors.get(kind, colors["info"])[0]
        label = ctk.CTkLabel(master, text=message, font=F_BOLD,
                             fg_color=fg, text_color="#FFFFFF",
                             corner_radius=10, padx=18, pady=10)
        label.place(relx=0.5, rely=0.96, anchor="s")
        Toast._current = label
        label.after(3200, label.destroy)


def toast(master, message: str, kind: str = "info") -> None:
    Toast(master, message, kind)


def pick_file(**kwargs) -> str | None:
    return filedialog.askopenfilename(**kwargs) or None


def pick_save(**kwargs) -> str | None:
    return filedialog.asksaveasfilename(**kwargs) or None
