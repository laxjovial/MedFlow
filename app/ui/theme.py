"""Desktop theme: colors, fonts, and appearance setup.

A calm clinical palette — deep teal accent, generous spacing — applied
consistently so every view looks like one product, not a widget demo.
"""

from __future__ import annotations

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


def apply_theme(mode: str = "system") -> None:
    """Set appearance and default widget styling once at startup."""
    ctk.set_appearance_mode(mode if mode in ("system", "light", "dark") else "system")
    ctk.set_default_color_theme("blue")     # base; we override with ACCENT
