"""Desktop theme: colors, fonts, and appearance setup.

The current controller-based UI uses the short tokens (ACCENT, F_BODY, etc.).
The older modular UI shell and its reusable dialogs still import the descriptive
tokens. Keep both names mapped to the same design system while the UI entry points
are reconciled; this is a compatibility contract, not a second theme.
"""

from __future__ import annotations

from dataclasses import dataclass

import customtkinter as ctk

ACCENT = "#0F766E"          # deep teal — calm, medical, not generic blue
ACCENT_DARK = "#0D6159"
ACCENT_SOFT = "#E6F4F2"
INK = "#16283C"
MUTED = "#64748B"
LINE = "#DFE7F0"
DANGER = "#B42318"
WARNING = "#B54708"
OK = "#067647"

FONT = "Segoe UI"
F_BODY = (FONT, 13)
F_SMALL = (FONT, 11)
F_BOLD = (FONT, 13, "bold")
F_H2 = (FONT, 20, "bold")
F_H3 = (FONT, 12, "bold")
F_STAT = (FONT, 30, "bold")


@dataclass(frozen=True)
class Palette:
    """Named colors used by the modular desktop shell and dialogs."""

    window: tuple[str, str] = ("#F7FAFC", "#111827")
    sidebar: tuple[str, str] = ("#F0F5F7", "#17212B")
    surface: tuple[str, str] = ("#FFFFFF", "#1F2937")
    surface_alt: tuple[str, str] = ("#EEF4F6", "#273548")
    border: tuple[str, str] = (LINE, "#374151")
    text: tuple[str, str] = (INK, "#F3F4F6")
    text_muted: tuple[str, str] = (MUTED, "#A7B4C2")
    text_inverse: tuple[str, str] = ("#FFFFFF", "#FFFFFF")
    accent: tuple[str, str] = (ACCENT, "#2DD4BF")
    accent_soft: tuple[str, str] = (ACCENT_SOFT, "#123B3A")
    accent_hover: tuple[str, str] = (ACCENT_DARK, "#0F766E")
    danger: tuple[str, str] = (DANGER, "#F87171")
    danger_hover: tuple[str, str] = ("#8F1D16", "#991B1B")
    warning: tuple[str, str] = (WARNING, "#FBBF24")
    success: tuple[str, str] = (OK, "#34D399")


# Compatibility contract for the older UI modules. Keep aliases explicit so
# imports fail loudly if a future redesign removes a token without a migration.
PALETTE = Palette()
FONT_BODY = F_BODY
FONT_BODY_BOLD = F_BOLD
FONT_HEADING = F_H2
FONT_TITLE = (FONT, 22, "bold")
FONT_SMALL = F_SMALL
FONT_TINY = (FONT, 10)
FONT_METRIC = F_STAT
GAP_XS = 6
GAP_SM = 10
GAP_MD = 16
GAP_LG = 24
RADIUS_MD = 12
SIDEBAR_WIDTH = 220
STATUS_BAR_HEIGHT = 28
NAV_ITEMS = (
    ("dashboard", "Dashboard", "⌂"),
    ("patients", "Patients", "♙"),
    ("activity", "Activity", "≡"),
    ("settings", "Settings", "⚙"),
)


def apply_theme(mode: str = "system") -> None:
    """Set appearance and default widget styling once at startup."""
    ctk.set_appearance_mode(mode if mode in ("system", "light", "dark") else "system")
    ctk.set_default_color_theme("blue")     # base; we override with ACCENT
