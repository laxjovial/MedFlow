"""The application shell.

Owns the window, the sidebar, the status bar and the routing between views. Views
are created once and kept; switching between them calls ``on_show`` rather than
rebuilding, so navigation is instant and a view always reads current data.

The shell is the only part of the UI that knows which views exist. A view asks to
navigate by name and never holds a reference to another view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from app.config.constants import APP_NAME, APP_TAGLINE, SYSTEM_ACTOR, STORAGE_MODE_NETWORK
from app.core.exceptions import MedFlowError
from app.ui.dialogs.confirm import ConfirmDialog, NotifyDialog
from app.ui.theme import (
    FONT_SMALL,
    FONT_TINY,
    FONT_TITLE,
    GAP_MD,
    GAP_SM,
    GAP_XS,
    NAV_ITEMS,
    PALETTE,
    RADIUS_MD,
    SIDEBAR_WIDTH,
    STATUS_BAR_HEIGHT,
)
from app.ui.views.activity import ActivityView
from app.ui.views.base import View
from app.ui.views.dashboard import DashboardView
from app.ui.views.patients import PatientsView
from app.ui.views.settings import SettingsView

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from app.container import Container

#: View key -> class. The keys match those in ``theme.NAV_ITEMS``.
VIEW_CLASSES: dict[str, type[View]] = {
    "dashboard": DashboardView,
    "patients": PatientsView,
    "activity": ActivityView,
    "settings": SettingsView,
}

DEFAULT_VIEW = "dashboard"


class MedFlowApp(ctk.CTk):
    """The main window."""

    def __init__(self, container: "Container", *, actor: str = SYSTEM_ACTOR) -> None:
        super().__init__()

        self.container = container
        #: Who changes are attributed to. A single-user desktop install has no
        #: login; when accounts exist this becomes the signed-in user, and nothing
        #: else in the application has to change.
        self.actor = actor

        self._views: dict[str, View] = {}
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._current: str | None = None

        self._configure_window()
        self._build_sidebar()
        self._build_status_bar()
        self._build_views()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-n>", lambda _event: self._global_new_patient())
        self.bind("<Control-q>", lambda _event: self._on_close())

        self.navigate(DEFAULT_VIEW)

    # ---------- window ----------

    def _configure_window(self) -> None:
        appearance = self.container.settings.appearance

        self.title(f"{APP_NAME} — {APP_TAGLINE}")
        self.geometry(f"{appearance.window_width}x{appearance.window_height}")
        self.minsize(appearance.min_window_width, appearance.min_window_height)
        self.configure(fg_color=PALETTE.window)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(
            self,
            width=SIDEBAR_WIDTH,
            corner_radius=0,
            fg_color=PALETTE.sidebar,
            border_width=0,
        )
        sidebar.grid(row=0, column=0, rowspan=2, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(2, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=GAP_SM, pady=(GAP_MD, GAP_SM))
        brand.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            brand, text=APP_NAME, font=FONT_TITLE, text_color=PALETTE.text, anchor="w"
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            brand, text=APP_TAGLINE, font=FONT_TINY, text_color=PALETTE.text_muted, anchor="w"
        ).grid(row=1, column=0, sticky="w")

        navigation = ctk.CTkFrame(sidebar, fg_color="transparent")
        navigation.grid(row=1, column=0, sticky="ew", padx=GAP_XS)
        navigation.grid_columnconfigure(0, weight=1)

        for row, (key, label, glyph) in enumerate(NAV_ITEMS):
            button = ctk.CTkButton(
                navigation,
                text=f"  {glyph}   {label}",
                command=lambda name=key: self.navigate(name),
                anchor="w",
                height=40,
                font=FONT_SMALL,
                fg_color="transparent",
                hover_color=PALETTE.surface_alt,
                text_color=PALETTE.text_muted,
                corner_radius=RADIUS_MD,
            )
            button.grid(row=row, column=0, sticky="ew", pady=(0, GAP_XS))
            self._nav_buttons[key] = button

        self._sidebar_footer = ctk.CTkLabel(
            sidebar,
            text="",
            font=FONT_TINY,
            text_color=PALETTE.text_muted,
            anchor="w",
            justify="left",
            wraplength=SIDEBAR_WIDTH - GAP_MD,
        )
        self._sidebar_footer.grid(
            row=3, column=0, sticky="ew", padx=GAP_SM, pady=(0, GAP_MD)
        )

    def _build_status_bar(self) -> None:
        bar = ctk.CTkFrame(
            self,
            height=STATUS_BAR_HEIGHT,
            corner_radius=0,
            fg_color=PALETTE.surface_alt,
        )
        bar.grid(row=1, column=1, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)

        self._status = ctk.CTkLabel(
            bar, text="Ready.", font=FONT_TINY, text_color=PALETTE.text_muted, anchor="w"
        )
        self._status.grid(row=0, column=0, sticky="ew", padx=GAP_SM)

        self._status_right = ctk.CTkLabel(
            bar, text="", font=FONT_TINY, text_color=PALETTE.text_muted, anchor="e"
        )
        self._status_right.grid(row=0, column=1, sticky="e", padx=GAP_SM)

    def _build_views(self) -> None:
        """Create every view once, hidden. Calls on_show when one is displayed."""
        for key, view_class in VIEW_CLASSES.items():
            view = view_class(self, app=self)
            view.grid(row=0, column=1, sticky="nsew")
            view.grid_remove()
            self._views[key] = view

    # ---------- routing ----------

    def navigate(self, key: str) -> None:
        """Show a view, refreshing it first."""
        target = self._views.get(key)
        if target is None:
            return

        if self._current is not None and self._current != key:
            previous = self._views.get(self._current)
            if previous is not None:
                previous.on_hide()
                previous.grid_remove()

        self._current = key
        target.grid()
        target.tkraise()
        target.on_show()

        for name, button in self._nav_buttons.items():
            active = name == key
            button.configure(
                fg_color=PALETTE.accent_soft if active else "transparent",
                text_color=PALETTE.accent if active else PALETTE.text_muted,
            )

        self._refresh_status_right()

    def current_view(self) -> View | None:
        return self._views.get(self._current) if self._current else None

    # ---------- status ----------

    def set_status(self, message: str) -> None:
        self._status.configure(text=message)

    def _refresh_status_right(self) -> None:
        settings = self.container.settings
        parts = [f"{self.container.patients.count()} patients", f"storage: {settings.storage.mode}"]
        if settings.storage.mode == STORAGE_MODE_NETWORK:
            parts.append("network mode is not implemented yet")
        self._status_right.configure(text=" · ".join(parts))

        location = str(settings.database_path)
        self._sidebar_footer.configure(text=f"{settings.storage.mode}\n{location}")

    # ---------- dialogs ----------

    def notify(self, title: str, message: str, *, tone: str = "info") -> None:
        NotifyDialog.show(self, title=title, message=message, tone=tone)  # type: ignore[arg-type]

    def confirm(
        self,
        *,
        title: str,
        message: str,
        detail: str = "",
        confirm_label: str = "Confirm",
        tone: str = "info",
    ) -> bool:
        return ConfirmDialog.ask(
            self,
            title=title,
            message=message,
            detail=detail,
            confirm_label=confirm_label,
            tone=tone,  # type: ignore[arg-type]
        )

    # ---------- appearance ----------

    def apply_appearance(self, mode: str, theme: str) -> None:
        """Record an appearance change and persist it.

        A failure to write is reported but not fatal: the change has already been
        applied to the running window, and refusing to accept it because a
        read-only directory cannot be written would be worse than losing it.
        """
        settings = self.container.settings
        settings.appearance.mode = mode
        settings.appearance.color_theme = theme

        try:
            settings.save()
        except MedFlowError as error:
            self.set_status(f"Appearance applied, but not saved: {error.message}")

    # ---------- keyboard ----------

    def _global_new_patient(self) -> None:
        self.navigate("patients")
        view = self._views.get("patients")
        if isinstance(view, PatientsView):
            view.create_patient()

    # ---------- shutdown ----------

    def _on_close(self) -> None:
        try:
            self.container.close()
        finally:
            self.destroy()


def build_application(container: "Container", *, actor: str = SYSTEM_ACTOR) -> MedFlowApp:
    """Construct the main window without entering the event loop.

    Separate from ``main`` so a test can build the whole interface and tear it down
    again without blocking.
    """
    ctk.set_appearance_mode(container.settings.appearance.mode)
    ctk.set_default_color_theme(container.settings.appearance.color_theme)
    return MedFlowApp(container, actor=actor)


__all__ = ["MedFlowApp", "build_application"]
