"""MedFlow desktop shell: sidebar navigation and view switching."""

from __future__ import annotations

import customtkinter as ctk

from app.ui.theme import ACCENT, ACCENT_SOFT, F_BODY, F_BOLD, F_SMALL, INK

NAV_ITEMS = (
    ("dashboard", "◧  Dashboard"),
    ("patients", "👥  Patients"),
    ("appointments", "🗓  Appointments"),
    ("reports", "📊  Reports"),
    ("activity", "⧗  Activity"),
    ("settings", "⚙  Settings"),
)


class MainWindow(ctk.CTk):
    """The application window: sidebar + header + swappable view frame."""

    def __init__(self, app):
        super().__init__()
        self.app = app                          # AppController (services + user)
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self.current_view = None

        self.title(f"MedFlow — {app.config.facility_name}")
        self.geometry("1180x740")
        self.minsize(980, 620)
        self._build_sidebar()
        self._build_header()

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(side="left", fill="both", expand=True)

        self.show("dashboard")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ #
    # chrome

    def _build_sidebar(self) -> None:
        bar = ctk.CTkFrame(self, width=210, corner_radius=0, fg_color="#F7FAF9")
        bar.pack(side="left", fill="y")

        logo = ctk.CTkFrame(bar, fg_color="transparent")
        logo.pack(fill="x", padx=18, pady=(20, 18))
        ctk.CTkLabel(logo, text="M", font=("Segoe UI", 20, "bold"),
                     text_color="#FFFFFF", fg_color=ACCENT,
                     corner_radius=10, width=40, height=40).pack(side="left")
        ctk.CTkLabel(logo, text="MedFlow", font=("Segoe UI", 17, "bold"),
                     text_color=INK).pack(side="left", padx=10)

        for key, label in NAV_ITEMS:
            btn = ctk.CTkButton(
                bar, text=label, anchor="w", font=F_BODY, height=40,
                corner_radius=9, fg_color="transparent", text_color=INK,
                hover_color=ACCENT_SOFT,
                command=lambda k=key: self.show(k))
            btn.pack(fill="x", padx=10, pady=2)
            self._nav_buttons[key] = btn

        footer = ctk.CTkFrame(bar, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=18, pady=16)
        ctk.CTkLabel(footer, text=self.app.user.display_name,
                     font=F_BOLD, anchor="w").pack(fill="x")
        ctk.CTkLabel(footer, text=f"{self.app.user.role}", font=F_SMALL,
                     text_color="#64748B", anchor="w").pack(fill="x")
        ctk.CTkButton(footer, text="Sign out", font=F_SMALL, height=30,
                      fg_color="transparent", border_width=1,
                      border_color="#DFE7F0", text_color=INK,
                      command=self.app.logout).pack(fill="x", pady=(8, 0))

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, height=58, corner_radius=0, fg_color="#FFFFFF")
        header.pack(side="top", fill="x")
        header.pack_propagate(False)
        self._header_title = ctk.CTkLabel(header, text="Dashboard",
                                          font=("Segoe UI", 17, "bold"),
                                          text_color=INK)
        self._header_title.pack(side="left", padx=22)
        self._header_right = ctk.CTkLabel(header, text="", font=F_SMALL,
                                          text_color="#64748B")
        self._header_right.pack(side="right", padx=22)

    # ------------------------------------------------------------------ #
    # navigation

    def show(self, key: str) -> None:
        for k, btn in self._nav_buttons.items():
            btn.configure(fg_color=ACCENT if k == key else "transparent",
                          text_color="#FFFFFF" if k == key else INK)
        self._header_title.configure(
            text=dict(NAV_ITEMS).get(key, key).split("  ")[-1])
        self._header_right.configure(
            text=f"{self.app.config.facility_name} · {self.app.today_label()}")

        if self.current_view is not None:
            self.current_view.destroy()
        view_cls = self.app.view_registry[key]
        self.current_view = view_cls(self.container, self.app)
        self.current_view.pack(fill="both", expand=True)

    def _on_close(self) -> None:
        self.app.shutdown()
        self.destroy()
