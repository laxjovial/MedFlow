"""Desktop login window: the front door of the workstation app.

A root ``CTk`` window (not a Toplevel) so it can run before any main
window exists; on success it sets ``app.user`` and closes itself.

Two ways in, mirroring the web login:

- **Password** — the classic credential prompt.
- **Pair with server** — a one-time code from a signed-in web session
  (password *or* Google), so Google-verified identities can sign in here
  without the desktop ever embedding a browser.

When the local database has no accounts at all, a first-run form offers
the same deal the web does: the first account becomes the administrator.
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
        self.geometry("420x520")
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

        self.error = ctk.CTkLabel(card, text="", font=F_SMALL,
                                  text_color=DANGER, wraplength=340,
                                  justify="left")
        self.error.pack(fill="x", padx=24, pady=(10, 0))

        if hasattr(self.app, "has_users") and not self.app.has_users():
            self._build_first_run(card)
        else:
            self._build_tabs(card)

        self.username.focus() if hasattr(self, "username") else None

    # ------------------------------------------------------------- tabs ----

    def _build_tabs(self, card: ctk.CTkFrame) -> None:
        self.tabs = ctk.CTkTabview(card, anchor="nw")
        self.tabs.pack(fill="both", expand=True, padx=24, pady=(12, 18))
        password_tab = self.tabs.add("Password")
        pair_tab = self.tabs.add("Pair with server")
        self._build_password_form(password_tab)
        self._build_pair_form(pair_tab)

    def _build_password_form(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(parent, text="Sign in to this workstation", font=F_BOLD,
                     text_color=MUTED).pack(anchor="w", pady=(10, 4))
        self.username = ctk.CTkEntry(parent, placeholder_text="Username",
                                     font=F_BODY, height=40)
        self.username.pack(fill="x", pady=(6, 8))
        self.password = ctk.CTkEntry(parent, placeholder_text="Password",
                                     show="•", font=F_BODY, height=40)
        self.password.pack(fill="x")
        self.password.bind("<Return>", lambda _e: self._submit_password())

        ctk.CTkButton(parent, text="Sign in", font=("Segoe UI", 14, "bold"),
                      height=44, fg_color=ACCENT, hover_color=ACCENT_DARK,
                      command=self._submit_password).pack(fill="x", pady=(12, 8))
        ctk.CTkLabel(parent, text="Accounts are managed in Settings → Staff.",
                     font=F_SMALL, text_color=MUTED).pack(pady=(4, 6))

    def _build_pair_form(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(parent, text="Pair with your MedFlow server",
                     font=F_BOLD, text_color=MUTED).pack(anchor="w",
                                                         pady=(10, 4))
        ctk.CTkLabel(
            parent,
            text=("Sign in on the web app (password or Google), click "
                  "\u201cPair desktop app\u201d, then type the one-time code here."),
            font=F_SMALL, text_color=MUTED, wraplength=320,
            justify="left").pack(anchor="w", pady=(0, 8))

        self.server_url = ctk.CTkEntry(
            parent, placeholder_text="Server URL — http://192.168.1.20:8000",
            font=F_BODY, height=40)
        self.server_url.pack(fill="x", pady=(6, 8))
        if getattr(self.app.config, "api_base_url", None):
            self.server_url.insert(0, self.app.config.api_base_url)

        self.pair_code = ctk.CTkEntry(
            parent, placeholder_text="Pairing code — ABCD-EFGH",
            font=F_BODY, height=40)
        self.pair_code.pack(fill="x")
        self.pair_code.bind("<Return>", lambda _e: self._submit_pair())

        ctk.CTkButton(parent, text="Pair & sign in",
                      font=("Segoe UI", 14, "bold"), height=44,
                      fg_color=ACCENT, hover_color=ACCENT_DARK,
                      command=self._submit_pair).pack(fill="x", pady=(12, 8))

    def _build_first_run(self, card: ctk.CTkFrame) -> None:
        ctk.CTkLabel(card, text="Welcome — create the administrator",
                     font=F_BOLD, text_color=MUTED).pack(anchor="w", padx=24,
                                                         pady=(14, 4))
        ctk.CTkLabel(
            card, text="The first account on this workstation becomes its "
                       "administrator. You can add staff later in Settings.",
            font=F_SMALL, text_color=MUTED, wraplength=330,
            justify="left").pack(anchor="w", padx=24, pady=(0, 8))
        self.username = ctk.CTkEntry(card, placeholder_text="Username",
                                     font=F_BODY, height=40)
        self.username.pack(fill="x", padx=24, pady=(6, 8))
        self.display_name = ctk.CTkEntry(card, placeholder_text="Your full name",
                                         font=F_BODY, height=40)
        self.display_name.pack(fill="x", padx=24, pady=(0, 8))
        self.password = ctk.CTkEntry(card, placeholder_text="Password (min 8 characters)",
                                     show="•", font=F_BODY, height=40)
        self.password.pack(fill="x", padx=24)
        self.password.bind("<Return>", lambda _e: self._submit_first_run())
        ctk.CTkButton(card, text="Create administrator",
                      font=("Segoe UI", 14, "bold"), height=44,
                      fg_color=ACCENT, hover_color=ACCENT_DARK,
                      command=self._submit_first_run).pack(fill="x", padx=24,
                                                           pady=(12, 8))

    # ----------------------------------------------------------- submit ----

    def _fail(self, message: str) -> None:
        self.error.configure(text=str(message))

    def _submit_password(self) -> None:
        self._fail("")
        try:
            self.app.authenticate(self.username.get().strip(),
                                  self.password.get())
        except Exception as exc:
            self._fail(exc)
            return
        self.destroy()

    def _submit_pair(self) -> None:
        self._fail("")
        url = self.server_url.get().strip()
        code = self.pair_code.get().strip()
        if not url or not code:
            self._fail("Both the server URL and the pairing code are needed.")
            return
        try:
            self.app.pair_with_server(url, code)
        except Exception as exc:
            self._fail(exc)
            return
        self.destroy()

    def _submit_first_run(self) -> None:
        self._fail("")
        username = self.username.get().strip()
        password = self.password.get()
        if len(password) < 8:
            self._fail("Password must be at least 8 characters.")
            return
        try:
            self.app.bootstrap_admin(username,
                                     self.display_name.get().strip(),
                                     password)
        except Exception as exc:
            self._fail(exc)
            return
        self.destroy()
