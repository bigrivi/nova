"""macOS hidden-titlebar chrome for the desktop window.

Applies the WorkBuddy-style layout on macOS only: the titled bar is removed
and native traffic lights (close/minimize/zoom) live as real ``NSButton``
instances inside the content view, so the whole window is web content with
region-matched header bands.

Why this shape: any surviving titlebar or toolbar view both paints over
and eats clicks for the top band (verified with ``hitTest_`` probes), so
only a titlebar-free window keeps custom header buttons visible *and*
clickable. Factory traffic lights keep native hover, press, and window
behavior; positions are re-pinned on every resize.

The styling is installed as a wrapper around pywebview's
``BrowserView.first_show``, which runs on the main thread inside
``webview.start()``. Post-show and resize re-applies hop threads via
``NSObject.performSelectorOnMainThread``. This deliberately avoids
``PyObjCTools.AppHelper`` (the frozen app does not bundle it).

Every entry point is a safe no-op on other platforms and never raises.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

TRAFFIC_LIGHT_LEFT = 14.0
TRAFFIC_LIGHT_STEP = 20.0
TRAFFIC_LIGHT_COUNT = 3
TRAFFIC_LIGHT_TAG_BASE = 1000
TITLEBAR_BAND_HEIGHT = 40.0
CORNER_RADIUS = 12.0
_HOOK_FLAG = "_nova_hidden_titlebar_installed"


def is_macos() -> bool:
    """Return True only on macOS."""
    return sys.platform == "darwin"


def traffic_light_x(index: int) -> float:
    """Return the x origin for a traffic light button by position.

    Args:
        index: Zero-based position (0=close, 1=minimize, 2=zoom).

    Returns:
        The x origin in points from the left window edge.
    """
    return TRAFFIC_LIGHT_LEFT + index * TRAFFIC_LIGHT_STEP


def _window_anchor_for_light(
    content: Any, native: Any, index: int, button_width: float
) -> tuple[float, float]:
    """Convert a band-centered light anchor from window to content coords.

    Uses AppKit's own conversion, so flipped and standard views position
    identically without assuming where the content origin lives.

    Args:
        content: The content view (button superview).
        native: The NSWindow handle.
        index: Zero-based light position.
        button_width: Native button width in points.

    Returns:
        Anchor point in content coordinates.
    """
    win_height = native.frame().size.height
    center = content.convertPoint_fromView_(
        (
            traffic_light_x(index) + button_width / 2.0,
            win_height - TITLEBAR_BAND_HEIGHT / 2.0,
        ),
        None,
    )
    return (center.x, center.y)


def _is_chrome_button(subview: Any) -> bool:
    """Return True if a subview is one of our traffic lights."""
    try:
        tag = subview.tag()
    except Exception:
        return False
    return TRAFFIC_LIGHT_TAG_BASE <= tag < TRAFFIC_LIGHT_TAG_BASE + 3


def _remove_titlebar(native: Any, appkit: Any) -> None:
    """Drop the titled mask so the window has no titlebar view at all.

    Closable/miniaturizable/resizable bits are preserved, so window-menu
    actions and keyboard shortcuts keep working.

    Args:
        native: The NSWindow handle.
        appkit: The AppKit module.
    """
    titled = getattr(appkit, "NSTitledWindowMask", 1)
    full_size = getattr(appkit, "NSFullSizeContentViewWindowMask", 1 << 15)
    native.setStyleMask_((native.styleMask() & ~titled) | full_size)
    native.setTitle_("")
    try:
        hidden = getattr(appkit, "NSWindowTitleHidden", 1)
        native.setTitleVisibility_(hidden)
    except Exception:
        logger.debug("Title visibility not adjustable", exc_info=True)


def _ensure_traffic_lights(native: Any, appkit: Any) -> None:
    """Create native traffic lights in the content view and position them.

    Buttons are tagged so re-applies reuse them instead of duplicating.
    Strays left from the titled era are removed.

    Args:
        native: The NSWindow handle.
        appkit: The AppKit module.
    """
    content = native.contentView()
    if content is None:
        return
    mask = native.styleMask()
    kinds = (
        appkit.NSWindowCloseButton,
        appkit.NSWindowMiniaturizeButton,
        appkit.NSWindowZoomButton,
    )
    for index, kind in enumerate(kinds):
        tag = TRAFFIC_LIGHT_TAG_BASE + index
        button = content.viewWithTag_(tag)
        if button is None:
            stray = native.standardWindowButton_(kind)
            if stray is not None:
                try:
                    stray.removeFromSuperview()
                except Exception:
                    logger.debug("Stray button removal failed", exc_info=True)
            button = appkit.NSWindow.standardWindowButton_forStyleMask_(kind, mask)
            if button is None:
                continue
            button.setTag_(tag)
            # Layer-backed: otherwise WKWebView's composited output paints
            # over plain sibling views and the lights stay invisible.
            button.setWantsLayer_(True)
            content.addSubview_(button)
        size = button.frame().size
        anchor_x, anchor_y = _window_anchor_for_light(
            content, native, index, size.width
        )
        button.setFrameOrigin_(
            (anchor_x - size.width / 2.0, anchor_y - size.height / 2.0)
        )


def _expand_webview(native: Any, appkit: Any) -> None:
    """Stretch the webview to fill the content view (minus chrome buttons).

    Args:
        native: The NSWindow handle.
        appkit: The AppKit module.
    """
    content = native.contentView()
    if content is None:
        return
    width_sizable = getattr(appkit, "NSViewWidthSizable", 2)
    height_sizable = getattr(appkit, "NSViewHeightSizable", 16)
    bounds = content.bounds()
    for subview in content.subviews():
        if _is_chrome_button(subview):
            continue
        subview.setFrame_(bounds)
        subview.setAutoresizingMask_(width_sizable | height_sizable)


def _round_corners(native: Any, appkit: Any) -> None:
    """Restore rounded corners and shadow lost with the titled mask.

    Clipping the content is not enough: the window itself paints an opaque
    square backdrop, so it must go transparent (clear) for the rounded
    content to read as a rounded window.

    Args:
        native: The NSWindow handle.
        appkit: The AppKit module.
    """
    content = native.contentView()
    if content is None:
        return
    try:
        content.setWantsLayer_(True)
        layer = content.layer()
        layer.setCornerRadius_(CORNER_RADIUS)
        layer.setMasksToBounds_(True)
    except Exception:
        logger.debug("Corner rounding failed", exc_info=True)
    try:
        native.setHasShadow_(True)
    except Exception:
        logger.debug("Shadow enable failed", exc_info=True)
    try:
        native.setOpaque_(False)
        native.setBackgroundColor_(appkit.NSColor.clearColor())
    except Exception:
        logger.debug("Window transparency failed", exc_info=True)


def _describe(native: Any) -> str:
    """Best-effort one-line summary of the chrome state for logs."""
    try:
        content = native.contentView()
        bounds = content.bounds()
        close = content.viewWithTag_(TRAFFIC_LIGHT_TAG_BASE)
        origin = close.frame().origin if close is not None else None
        try:
            flipped = bool(content.isFlipped())
        except Exception:
            flipped = None
        return (
            f"mask={int(native.styleMask())} "
            f"content={bounds.size.width}x{bounds.size.height} "
            f"flipped={flipped} "
            f"close=({origin.x if origin else None},"
            f"{origin.y if origin else None})"
        )
    except Exception:
        return "unavailable"


def _apply_hidden_titlebar(native: Any, appkit: Any) -> None:
    """Apply borderless-style chrome to an NSWindow handle.

    Must run on the main thread.

    Args:
        native: The NSWindow handle.
        appkit: The AppKit module.
    """
    _remove_titlebar(native, appkit)
    _expand_webview(native, appkit)
    _ensure_traffic_lights(native, appkit)
    _round_corners(native, appkit)
    logger.info("macOS hidden titlebar applied: %s", _describe(native))


_APPLIER_CLS: Any | None = None
_APPLIER_NATIVE: Any = None


def _apply_on_main_thread(native: Any) -> bool:
    """Re-apply chrome on the main thread without AppHelper.

    The frozen app does not bundle ``PyObjCTools``, so main-thread hops go
    through ``NSObject.performSelectorOnMainThread`` (Foundation is always
    bundled with the cocoa backend).

    Args:
        native: The NSWindow handle.

    Returns:
        True if the fixup was scheduled, False otherwise.
    """
    global _APPLIER_CLS, _APPLIER_NATIVE
    try:
        from Foundation import NSObject  # type: ignore[import-not-found]
    except ImportError:
        logger.debug("Foundation unavailable; skipping post-show fixup")
        return False
    if _APPLIER_CLS is None:

        class _Applier(NSObject):  # type: ignore[no-redef]
            def apply_(self, _sender: Any) -> None:
                try:
                    import AppKit  # type: ignore[import-not-found]

                    _apply_hidden_titlebar(_APPLIER_NATIVE, AppKit)
                except Exception:
                    logger.exception("Post-show hidden-titlebar fixup failed")
                # Showing swaps the content view out from under the
                # pre-show styling; one delayed pass lands on the final
                # instance. Resizes re-apply through _on_resized.
                try:
                    self.performSelector_withObject_afterDelay_("reapply:", None, 0.5)
                except Exception:
                    logger.debug("Delayed re-apply failed", exc_info=True)

            def reapply_(self, _sender: Any) -> None:
                try:
                    import AppKit  # type: ignore[import-not-found]

                    _apply_hidden_titlebar(_APPLIER_NATIVE, AppKit)
                except Exception:
                    logger.exception("Delayed hidden-titlebar fixup failed")

        _APPLIER_CLS = _Applier
    _APPLIER_NATIVE = native
    try:
        applier = _APPLIER_CLS.alloc().init()
        applier.performSelectorOnMainThread_withObject_waitUntilDone_(
            "apply:", None, False
        )
    except Exception:
        logger.exception("Failed to schedule post-show fixup")
        return False
    return True


def _on_shown(window: Any) -> None:
    """pywebview shown-event handler: post-show fixup on the main thread."""
    if not is_macos():
        return
    native = getattr(window, "native", None)
    if native is None:
        return
    _apply_on_main_thread(native)


def _on_resized(window: Any, *_args: Any) -> None:
    """pywebview resized-event handler: re-pin chrome on the main thread."""
    if not is_macos():
        return
    native = getattr(window, "native", None)
    if native is None:
        return
    _apply_on_main_thread(native)


def _install_first_show_hook(browser_view_cls: Any | None = None) -> bool:
    """Wrap ``BrowserView.first_show`` to style each window on creation.

    Args:
        browser_view_cls: The pywebview ``BrowserView`` class. Resolved
            from ``webview.platforms.cocoa`` when omitted (injectable for
            tests).

    Returns:
        True if the hook is installed, False otherwise.
    """
    if not is_macos():
        return False
    if browser_view_cls is None:
        try:
            from webview.platforms import cocoa
        except ImportError:
            logger.debug("pywebview cocoa backend unavailable")
            return False
        browser_view_cls = cocoa.BrowserView
    original = getattr(browser_view_cls, "first_show", None)
    if original is None:
        logger.debug("BrowserView.first_show not found; skipping")
        return False
    if getattr(original, _HOOK_FLAG, False):
        return True

    def first_show(browser_view: Any) -> Any:
        try:
            import AppKit  # type: ignore[import-not-found]

            _apply_hidden_titlebar(browser_view.window, AppKit)
        except Exception:
            logger.exception("Failed to apply macOS hidden titlebar")
        try:
            events = browser_view.pywebview_window.events
            events.shown += _on_shown
            events.resized += _on_resized
        except Exception:
            logger.debug("Failed to subscribe window events", exc_info=True)
        return original(browser_view)

    setattr(first_show, _HOOK_FLAG, True)
    browser_view_cls.first_show = first_show
    return True


def wire_hidden_titlebar() -> None:
    """Install macOS hidden-titlebar chrome for desktop windows.

    Safe on every platform: no-op outside macOS. Call once before
    ``webview.start()``; the styling runs per window on the main thread.
    """
    _install_first_show_hook()
