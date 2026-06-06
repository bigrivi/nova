from __future__ import annotations

from dataclasses import dataclass

from textual.color import Color
from textual.theme import BUILTIN_THEMES


@dataclass(frozen=True)
class ThemeColors:
    """Resolved hex colors from the current Textual theme, for use in Rich Text."""

    primary: str
    secondary: str
    success: str
    warning: str
    error: str
    foreground: str
    text_muted: str
    text_disabled: str
    surface: str
    panel: str
    background: str


def _blend(fg: Color, bg: Color, ratio: float) -> str:
    return fg.blend(bg, ratio).hex6


def _theme_for_app(app):
    theme_name = getattr(app, "theme", "textual-dark")
    theme = getattr(app, "current_theme", None)
    if theme is not None:
        return theme
    if hasattr(app, "get_theme"):
        theme = app.get_theme(theme_name)
        if theme is not None:
            return theme
    return BUILTIN_THEMES["textual-dark"]


def _hex(value: str) -> str:
    return Color.parse(value).hex6


def get_theme_colors(app) -> ThemeColors:
    """Extract hex colors from the app's current theme for use in Rich Text."""
    theme = _theme_for_app(app)
    variables = theme.to_color_system().generate()
    fg = Color.parse(variables["foreground"])
    bg = Color.parse(variables["background"])
    return ThemeColors(
        primary=_hex(variables["primary"]),
        secondary=_hex(variables["secondary"]),
        success=_hex(variables["success"]),
        warning=_hex(variables["warning"]),
        error=_hex(variables["error"]),
        foreground=fg.hex6,
        text_muted=_blend(fg, bg, 0.4),
        text_disabled=_blend(fg, bg, 0.6),
        surface=_hex(variables["surface"]),
        panel=_hex(variables["panel"]),
        background=bg.hex6,
    )
