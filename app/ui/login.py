"""Desktop login window: the front door of the workstation app.

A root ``CTk`` window (not a Toplevel) so it can run before any main
window exists; on success it sets ``app.user`` and closes itself.
"""

from __future__ import annotations

import customtkinter as ctk

from app.ui.theme import (
    ACCENT, ACCENT_DARK, DANGER, F_BODY, F_BOLD, F_SMALL, INK, MUTED,
)


class LoginDialog(ctk.CTk):
    """Credential prompt shown at startup; sets ``app.user`` on success."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.title("Sign in — MedFlow")
        self.geometry("400x470")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        card = ctk.CTkFrame(self, corner_radius=16, border_width=1,
                            border_color="#DFE7F0")
        card.pack(expand=True, fill="both", padx=18, pady=18)

        brand = ctk.CTkFrame(card, fg_color="transparent")
        brand.pack(fill="x", padx=24, pady=(26, 6))
        ctk.CTkLabel(brand, text="M", font=("Segoe UI", 22, "bold"),
                     text_color="#FFFFFF", fg_color=ACCENT, corner_radius=12,
                     width=48, height=48).pack(side="left")
        title = ctk.CTkFrame(brand, fg_color="transparent")
        title.pack(side="left", padx=12)
        ctk.CTkLabel(title, text="MedFlow", font=("Segoe UI", 20, "bold"),
                     text_color=INK).pack(anchor="w")
        ctk.CTkLabel(title, text="Local-first clinic workspace", font=F_SMALL,
                     text_color=MUTED).pack(anchor="w")

        ctk.CTkLabel(card, text="Sign in to this workstation", font=F_BOLD,
                     text_color=MUTED).pack(anchor="w", padx=24, pady=(16, 4))

        self.username = ctk.CTkEntry(card, placeholder_text="Username",
                                     font=F_BODY, height=40)
        self.username.pack(fill="x", padx=24, pady=(6, 8))
        self.password = ctk.CTkEntry(card, placeholder_text="Password",
                                     show="•", font=F_BODY, height=40)
        self.password.pack(fill="x", padx=24)
        self.password.bind("<Return>", lambda _e: self._submit())

        self.error = ctk.CTkLabel(card, text="", font=F_SMALL,
                                  text_color=DANGER, wraplength=320,
                                  justify="left")
        self.error.pack(fill="x", padx=24, pady=(6, 0))

        ctk.CTkButton(card, text="Sign in", font=("Segoe UI", 14, "bold"),
                      height=44, fg_color=ACCENT, hover_color=ACCENT_DARK,
                      command=self._submit).pack(fill="x", padx=24, pady=(12, 8))

        ctk.CTkLabel(card, text="Accounts are managed in Settings → Staff.",
                     font=F_SMALL, text_color=MUTED).pack(pady=(4, 20))

        self.username.focus()

    def _submit(self) -> None:
        try:
            self.app.authenticate(self.username.get().strip(),
                                  self.password.get())
        except Exception as exc:
            self.error.configure(text=str(exc))
            return
        self.destroy()
