"""Theme tokens.

Every colour, size and spacing value the interface uses is named here. Views refer
to tokens rather than literals, so the whole application can be restyled from one
file and no widget silently disagrees with the rest of the app.

Colours are ``(light, dark)`` pairs, which is the form CustomTkinter expects: it
picks the correct entry for the active appearance mode, so a view never has to ask
which mode is running.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    """Named colours, each a light/dark pair."""

    # Surfaces, from furthest back to furthest forward.
    window: tuple[str, str] = ("#f4f6fa", "#14161c")
    surface: tuple[str, str] = ("#ffffff", "#1c1f27")
    surface_alt: tuple[str, str] = ("#eef1f7", "#232733")
    sidebar: tuple[str, str] = ("#ffffff", "#181b22")
    border: tuple[str, str] = ("#dde2ec", "#2b303c")

    # Text.
    text: tuple[str, str] = ("#1a1d24", "#eef0f4")
    text_muted: tuple[str, str] = ("#5c6470", "#9aa3b2")
    text_inverse: tuple[str, str] = ("#ffffff", "#ffffff")

    # Accents.
    accent: tuple[str, str] = ("#2563eb", "#3b82f6")
    accent_hover: tuple[str, str] = ("#1d4ed8", "#2563eb")
    accent_soft: tuple[str, str] = ("#e5edff", "#1e2b45")

    # Status.
    success: tuple[str, str] = ("#15803d", "#4ade80")
    warning: tuple[str, str] = ("#b45309", "#fbbf24")
    danger: tuple[str, str] = ("#b91c1c", "#f87171")
    danger_hover: tuple[str, str] = ("#991b1b", "#ef4444")
    neutral: tuple[str, str] = ("#64748b", "#94a3b8")

    # Row striping, kept barely visible.
    row_alt: tuple[str, str] = ("#f8fafc", "#1f232c")


PALETTE = Palette()

# ---------- geometry ----------

#: Base spacing unit. Every gap in the interface is a multiple of this, which is
#: what keeps unrelated views looking like they belong to one application.
UNIT = 4

GAP_XS = UNIT
GAP_SM = UNIT * 2
GAP_MD = UNIT * 4
GAP_LG = UNIT * 6
GAP_XL = UNIT * 8

RADIUS_SM = 6
RADIUS_MD = 10
RADIUS_LG = 14

# ---------- typography ----------

FONT_FAMILY = "Segoe UI"  # CustomTkinter falls back automatically where absent

FONT_DISPLAY = (FONT_FAMILY, 26, "bold")
FONT_TITLE = (FONT_FAMILY, 19, "bold")
FONT_HEADING = (FONT_FAMILY, 15, "bold")
FONT_BODY = (FONT_FAMILY, 13)
FONT_BODY_BOLD = (FONT_FAMILY, 13, "bold")
FONT_SMALL = (FONT_FAMILY, 12)
FONT_TINY = (FONT_FAMILY, 11)
FONT_METRIC = (FONT_FAMILY, 30, "bold")
FONT_MONO = ("Consolas", 12)

# ---------- layout ----------

SIDEBAR_WIDTH = 212
STATUS_BAR_HEIGHT = 30
SEARCH_DEBOUNCE_MS = 220

#: Sidebar entries: internal view key, label, and the glyph shown beside it.
NAV_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("dashboard", "Dashboard", "▦"),
    ("patients", "Patients", "☰"),
    ("activity", "Activity", "⟳"),
    ("settings", "Settings", "⚙"),
)
