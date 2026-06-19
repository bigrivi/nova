"""One Dark-inspired syntax theme for tree-sitter token groups."""

from opentui.components._syntax_highlight import SyntaxStyle
from opentui.structs import RGBA

_r = RGBA


def default_syntax_style() -> SyntaxStyle:
    return SyntaxStyle.from_styles({
        # ── Base ────────────────────────────────────────────────
        "default": {"fg": _r(0.76, 0.79, 0.82, 1)},

        # ── Keywords (control flow, declarations) ───────────────
        "keyword":              {"fg": _r(0.78, 0.33, 0.55, 1), "bold": False},
        "keyword.control":      {"fg": _r(0.78, 0.33, 0.55, 1)},
        "keyword.operator":     {"fg": _r(0.78, 0.33, 0.55, 1)},
        "keyword.import":       {"fg": _r(0.78, 0.33, 0.55, 1)},
        "keyword.type":         {"fg": _r(0.78, 0.33, 0.55, 1)},

        # ── Strings ─────────────────────────────────────────────
        "string":               {"fg": _r(0.60, 0.76, 0.34, 1)},
        "string.special":       {"fg": _r(0.60, 0.76, 0.34, 1)},
        "string.documentation": {"fg": _r(0.60, 0.76, 0.34, 1)},
        "string.regexp":        {"fg": _r(0.60, 0.76, 0.34, 1)},

        # ── Comments ────────────────────────────────────────────
        "comment":              {"fg": _r(0.44, 0.47, 0.51, 1), "italic": True},

        # ── Types ───────────────────────────────────────────────
        "type":                 {"fg": _r(0.85, 0.66, 0.32, 1)},
        "type.builtin":         {"fg": _r(0.85, 0.66, 0.32, 1)},

        # ── Functions / methods ─────────────────────────────────
        "function":             {"fg": _r(0.38, 0.61, 0.84, 1)},
        "function.method":      {"fg": _r(0.38, 0.61, 0.84, 1)},
        "function.call":        {"fg": _r(0.38, 0.61, 0.84, 1)},

        # ── Numbers ─────────────────────────────────────────────
        "number":               {"fg": _r(0.85, 0.55, 0.30, 1)},

        # ── Variables / parameters ──────────────────────────────
        "variable":             {"fg": _r(0.86, 0.43, 0.34, 1)},
        "parameter":            {"fg": _r(0.86, 0.43, 0.34, 1)},
        "property":             {"fg": _r(0.86, 0.43, 0.34, 1)},

        # ── Constants (True/False/None, ALL_CAPS) ──────────────
        "constant":             {"fg": _r(0.85, 0.55, 0.30, 1)},
        "constant.builtin":     {"fg": _r(0.85, 0.55, 0.30, 1)},

        # ── Operators / punctuation ─────────────────────────────
        "operator":             {"fg": _r(0.64, 0.69, 0.73, 1)},
        "punctuation":          {"fg": _r(0.56, 0.59, 0.63, 1)},
        "punctuation.bracket":  {"fg": _r(0.64, 0.69, 0.73, 1)},
        "punctuation.delimiter":{"fg": _r(0.56, 0.59, 0.63, 1)},

        # ── Tags (HTML/XML) ─────────────────────────────────────
        "tag":                  {"fg": _r(0.78, 0.33, 0.55, 1)},

        # ── Markdown (inside markdown content) ──────────────────
        "markup.heading":       {"fg": _r(0.90, 0.42, 0.42, 1), "bold": True},
        "markup.heading.1":     {"fg": _r(0.90, 0.42, 0.42, 1), "bold": True},
        "markup.heading.2":     {"fg": _r(0.85, 0.55, 0.30, 1), "bold": True},
        "markup.heading.3":     {"fg": _r(0.85, 0.66, 0.32, 1), "bold": True},
        "markup.heading.4":     {"fg": _r(0.60, 0.76, 0.34, 1), "bold": True},
        "markup.heading.5":     {"fg": _r(0.44, 0.67, 0.93, 1), "bold": True},
        "markup.heading.6":     {"fg": _r(0.76, 0.47, 0.78, 1), "bold": True},
        "markup.bold":          {"fg": _r(0.86, 0.43, 0.34, 1), "bold": True},
        "markup.italic":        {"fg": _r(0.86, 0.43, 0.34, 1), "italic": True},
        "markup.link":          {"fg": _r(0.38, 0.61, 0.84, 1), "underline": True},
        "markup.list":          {"fg": _r(0.85, 0.55, 0.30, 1)},
        "markup.list.checked":  {"fg": _r(0.60, 0.76, 0.34, 1)},
        "markup.list.unchecked":{"fg": _r(0.56, 0.59, 0.63, 1)},
        "markup.raw":           {"fg": _r(0.60, 0.76, 0.34, 1)},

        # ── Embedded code (backtick fence) ──────────────────────
        "embedded":             {"fg": _r(0.76, 0.79, 0.82, 1)},
    })


__all__ = ["default_syntax_style"]
