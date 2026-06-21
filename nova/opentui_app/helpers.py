from typing import Callable

from opentui.hooks import get_renderer


def delay(seconds: float, callback: Callable) -> None:
    """Schedule *callback* to fire after *seconds* using request_animation_frame."""
    renderer = get_renderer()
    if renderer is None:
        callback()
        return
    elapsed = [0.0]

    def tick(dt: float) -> None:
        elapsed[0] += dt
        if elapsed[0] >= seconds:
            callback()
        else:
            renderer.request_animation_frame(tick)

    renderer.request_animation_frame(tick)


_SNAP_CHARS = frozenset(" ,.!?;:])\n")


def _step(remaining: int) -> int:
    if remaining <= 12:
        return 2
    if remaining <= 48:
        return 4
    if remaining <= 96:
        return 8
    return min(24, max(8, remaining // 8))


def next_reveal_boundary(text: str, start: int) -> int:
    """Advance reveal position by a variable step, snapping to punctuation."""
    end = min(len(text), start + _step(len(text) - start))
    max_snap = min(len(text), end + 8)
    for i in range(end, max_snap):
        if text[i] in _SNAP_CHARS:
            return i + 1
    return end


def heal(text: str) -> str:
    """Auto-close incomplete markdown formatting markers during streaming."""
    if text.count("**") % 2 == 1:
        text += "**"
    stripped = text.replace("**", "")
    if stripped.count("*") % 2 == 1:
        text += "*"
    if text.count("`") % 2 == 1:
        text += "`"
    return text


def ensure_closed_fences(text: str) -> str:
    """Artificially close unclosed code fences so the parser creates code tokens."""
    lines = text.split("\n")
    fence: str | None = None
    for line in lines:
        s = line.strip()
        if fence is None:
            import re
            m = re.match(r"^(````?|~~~)(?:\s*\w*)?$", s)
            if m:
                fence = m.group(1)
        else:
            if s.rstrip() == fence:
                fence = None
    if fence is not None:
        text += "\n" + fence
    return text
