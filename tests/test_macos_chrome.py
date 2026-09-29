"""Tests for macOS hidden-titlebar chrome (all GUI deps mocked)."""

from __future__ import annotations

import sys
import types

import pytest

from nova.desktop import macos_chrome


class _FakeOrigin:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


class _FakeSize:
    def __init__(self, width: float, height: float) -> None:
        self.width = width
        self.height = height


class _FakeRect:
    def __init__(self, x: float, y: float, width: float, height: float) -> None:
        self.origin = _FakeOrigin(x, y)
        self.size = _FakeSize(width, height)


class _FakeButton:
    def __init__(self, x: float, y: float, width: float = 12.0) -> None:
        self._frame = _FakeRect(x, y, width, width)
        self._tag = 0
        self.origins: list[tuple[float, float]] = []
        self.removed = False

    def frame(self) -> _FakeRect:
        return self._frame

    def setFrameOrigin_(self, origin: tuple[float, float]) -> None:
        self._frame.origin = _FakeOrigin(origin[0], origin[1])
        self.origins.append((origin[0], origin[1]))

    def tag(self) -> int:
        return self._tag

    def setTag_(self, tag: int) -> None:
        self._tag = tag

    def setWantsLayer_(self, value: bool) -> None:
        self.layered = value

    def removeFromSuperview(self) -> None:
        self.removed = True

    def setFrame_(self, frame: object) -> None:
        self.frame_value = frame

    def setAutoresizingMask_(self, mask: int) -> None:
        self.mask = mask


class _FakeWebView:
    def __init__(self) -> None:
        self.frame: object = None
        self.mask: int | None = None

    def tag(self) -> int:
        return 0

    def setFrame_(self, frame: object) -> None:
        self.frame = frame

    def setAutoresizingMask_(self, mask: int) -> None:
        self.mask = mask


class _FakeLayer:
    def __init__(self) -> None:
        self.radius: float | None = None
        self.masked: bool | None = None

    def setCornerRadius_(self, value: float) -> None:
        self.radius = value

    def setMasksToBounds_(self, value: bool) -> None:
        self.masked = value


class _FakeContent:
    def __init__(self, width: float = 900.0, height: float = 650.0) -> None:
        self.width = width
        self.height = height
        self.webview = _FakeWebView()
        self.views: list[object] = [self.webview]
        self.layer_value = _FakeLayer()

    def bounds(self) -> _FakeRect:
        return _FakeRect(0.0, 0.0, self.width, self.height)

    def subviews(self) -> list[object]:
        return self.views

    def viewWithTag_(self, tag: int) -> object | None:
        for view in self.views:
            if getattr(view, "tag", lambda: 0)() == tag:
                return view
        return None

    def convertPoint_fromView_(
        self, point: tuple[float, float], _view: object
    ) -> _FakeOrigin:
        return _FakeOrigin(point[0], point[1])

    def isFlipped(self) -> bool:
        return False

    def addSubview_(self, view: object) -> None:
        self.views.append(view)

    def setWantsLayer_(self, value: bool) -> None:
        self.layered = value

    def layer(self) -> _FakeLayer:
        return self.layer_value


class _FakeNative:
    TITLED = 1
    CLOSABLE = 2
    MINIATURIZABLE = 4
    RESIZABLE = 8

    def __init__(self) -> None:
        self.mask = (
            self.TITLED | self.CLOSABLE | self.MINIATURIZABLE | self.RESIZABLE
        )
        self.title: str | None = "Nova"
        self.visibility: int | None = None
        self.shadow: bool | None = None
        self.opaque: bool | None = None
        self.background: object = None
        self.win_width = 900.0
        self.win_height = 650.0
        self.content = _FakeContent(self.win_width, self.win_height)
        self.content = _FakeContent()
        self.strays: dict[int, _FakeButton] = {}
        self.factory_calls = 0

    def styleMask(self) -> int:
        return self.mask

    def setStyleMask_(self, mask: int) -> None:
        self.mask = mask

    def setTitle_(self, title: str) -> None:
        self.title = title

    def setTitleVisibility_(self, value: int) -> None:
        self.visibility = value

    def setHasShadow_(self, value: bool) -> None:
        self.shadow = value

    def setOpaque_(self, value: bool) -> None:
        self.opaque = value

    def setBackgroundColor_(self, color: object) -> None:
        self.background = color

    def contentView(self) -> _FakeContent:
        return self.content

    def frame(self) -> _FakeRect:
        return _FakeRect(0.0, 0.0, self.win_width, self.win_height)

    def standardWindowButton_(self, kind: int) -> _FakeButton | None:
        return self.strays.get(kind)


class _FakeShownEvent:
    def __init__(self) -> None:
        self.handlers: list[object] = []

    def __iadd__(self, handler: object) -> "_FakeShownEvent":
        self.handlers.append(handler)
        return self


class _FakePywebviewEvents:
    def __init__(self) -> None:
        self.shown = _FakeShownEvent()
        self.resized = _FakeShownEvent()


class _FakePywebviewWindow:
    def __init__(self) -> None:
        self.events = _FakePywebviewEvents()


def _install_fake_appkit(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("AppKit")
    module.NSTitledWindowMask = 1
    module.NSFullSizeContentViewWindowMask = 1 << 15
    module.NSWindowTitleHidden = 1
    module.NSWindowCloseButton = 0
    module.NSWindowMiniaturizeButton = 1
    module.NSWindowZoomButton = 2
    module.NSViewWidthSizable = 2
    module.NSViewHeightSizable = 16

    class _FakeNSColor:
        @staticmethod
        def clearColor() -> str:
            return "clear"

    module.NSColor = _FakeNSColor

    class _FakeNSWindow:
        @classmethod
        def standardWindowButton_forStyleMask_(
            cls, kind: int, mask: int
        ) -> _FakeButton:
            return _FakeButton(0.0, 0.0)

    module.NSWindow = _FakeNSWindow
    monkeypatch.setitem(sys.modules, "AppKit", module)


def _install_fake_foundation(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("Foundation")

    class _FakeNSObject:
        @classmethod
        def alloc(cls) -> "_FakeNSObject":
            return cls()

        def init(self) -> "_FakeNSObject":
            return self

        def performSelectorOnMainThread_withObject_waitUntilDone_(
            self, _selector: str, _obj: object, _wait: bool
        ) -> bool:
            self.apply_(_obj)  # type: ignore[attr-defined]
            return True

        def performSelector_withObject_afterDelay_(
            self, _selector: str, _obj: object, _delay: float
        ) -> bool:
            if _selector == "reapply:":
                self.reapply_(_obj)  # type: ignore[attr-defined]
            return True

    module.NSObject = _FakeNSObject
    monkeypatch.setitem(sys.modules, "Foundation", module)


def test_traffic_light_geometry() -> None:
    assert macos_chrome.traffic_light_x(0) == 14.0
    assert macos_chrome.traffic_light_x(1) == 34.0
    assert macos_chrome.traffic_light_x(2) == 54.0
    assert macos_chrome.TITLEBAR_BAND_HEIGHT == 40.0


def test_non_macos_skips_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    class _Browser:
        def first_show(self) -> str:
            return "shown"

    assert macos_chrome._install_first_show_hook(_Browser) is False


def test_hook_missing_first_show_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")

    class _Bare:
        pass

    assert macos_chrome._install_first_show_hook(_Bare) is False


def test_hook_applies_borderless_chrome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    _install_fake_appkit(monkeypatch)
    native = _FakeNative()
    native.strays = {0: _FakeButton(9.0, 6.0)}

    class _Browser:
        calls = 0

        def __init__(self, handle: _FakeNative) -> None:
            self.window = handle
            self.pywebview_window = _FakePywebviewWindow()

        def first_show(self) -> str:
            type(self).calls += 1
            return "shown"

    assert macos_chrome._install_first_show_hook(_Browser) is True
    assert macos_chrome._install_first_show_hook(_Browser) is True

    browser = _Browser(native)
    assert browser.first_show() == "shown"
    assert _Browser.calls == 1
    assert len(browser.pywebview_window.events.shown.handlers) == 1
    assert len(browser.pywebview_window.events.resized.handlers) == 1

    assert native.mask & 1 == 0
    assert native.mask & (1 << 15)
    assert native.mask & _FakeNative.RESIZABLE
    assert native.title == ""
    webview_frame = native.content.webview.frame
    assert webview_frame.size.width == 900.0
    assert webview_frame.size.height == 650.0
    assert native.content.webview.mask == 18
    assert native.content.layer_value.radius == 12.0
    assert native.content.layer_value.masked is True
    assert native.shadow is True
    assert native.opaque is False
    assert native.background == "clear"
    assert native.strays[0].removed is True
    for index in range(3):
        button = native.content.viewWithTag_(1000 + index)
        assert button is not None
        assert button.layered is True
        assert button.origins == [(14.0 + index * 20.0, 624.0)]


def test_reapply_reuses_buttons_and_repins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    _install_fake_appkit(monkeypatch)
    appkit = sys.modules["AppKit"]
    native = _FakeNative()

    macos_chrome._apply_hidden_titlebar(native, appkit)
    assert len(native.content.views) == 4
    native.win_height = 750.0
    native.content.height = 750.0
    macos_chrome._apply_hidden_titlebar(native, appkit)

    assert len(native.content.views) == 4
    button = native.content.viewWithTag_(1000)
    assert button.origins == [(14.0, 624.0), (14.0, 724.0)]


def test_expand_skips_chrome_buttons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    _install_fake_appkit(monkeypatch)
    native = _FakeNative()
    light = _FakeButton(20.0, 618.0)
    light.setTag_(1000)
    native.content.views.append(light)
    macos_chrome._expand_webview(native, sys.modules["AppKit"])
    assert not hasattr(light, "frame_value")
    webview_frame = native.content.webview.frame
    assert webview_frame.size.width == 900.0
    assert webview_frame.size.height == 650.0


def test_post_show_fixup_applies_styling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    _install_fake_appkit(monkeypatch)
    _install_fake_foundation(monkeypatch)
    monkeypatch.setattr(macos_chrome, "_APPLIER_CLS", None)

    native = _FakeNative()
    window = _FakePywebviewWindow()
    window.native = native  # type: ignore[attr-defined]
    macos_chrome._on_shown(window)

    assert native.mask & 1 == 0
    assert native.title == ""
    assert native.content.viewWithTag_(1000) is not None
    button = native.content.viewWithTag_(1000)
    assert button.origins == [(14.0, 624.0), (14.0, 624.0)]


def test_resized_handler_reapplies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    _install_fake_appkit(monkeypatch)
    _install_fake_foundation(monkeypatch)
    monkeypatch.setattr(macos_chrome, "_APPLIER_CLS", None)

    native = _FakeNative()
    window = _FakePywebviewWindow()
    window.native = native  # type: ignore[attr-defined]
    macos_chrome._on_resized(window, 1100, 750)
    assert native.title == ""
    assert native.content.viewWithTag_(1002) is not None


def test_post_show_fixup_off_macos_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    native = _FakeNative()
    window = _FakePywebviewWindow()
    window.native = native  # type: ignore[attr-defined]
    macos_chrome._on_shown(window)
    assert native.title == "Nova"


def test_post_show_fixup_without_foundation_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "Foundation", None)
    monkeypatch.setattr(macos_chrome, "_APPLIER_CLS", None)
    assert macos_chrome._apply_on_main_thread(_FakeNative()) is False


def test_wire_is_noop_off_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    macos_chrome.wire_hidden_titlebar()
