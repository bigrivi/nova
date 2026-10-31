"""The TUI bundle has to resolve for a pip-installed Nova, not only a checkout.

`nova/__main__._run_tui` used to reject a missing `tui/` directory before asking
`_build_tui` for a path, which made the bundle the install script downloads into
`$NOVA_HOME/tui` unreachable. These pin the resolution order.
"""

from __future__ import annotations

from pathlib import Path

from nova.__main__ import _build_tui


def test_downloaded_bundle_is_used_without_a_checkout(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    bundle = home / "tui" / "dist" / "index.js"
    bundle.parent.mkdir(parents=True)
    bundle.write_text("// bundle", encoding="utf-8")
    monkeypatch.setenv("NOVA_HOME", str(home))

    resolved = _build_tui(tmp_path / "no-repo", tmp_path / "no-repo" / "tui")

    assert resolved == bundle


def test_checkout_bundle_wins_over_the_downloaded_one(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    downloaded = home / "tui" / "dist" / "index.js"
    downloaded.parent.mkdir(parents=True)
    downloaded.write_text("// downloaded", encoding="utf-8")
    monkeypatch.setenv("NOVA_HOME", str(home))

    checkout_tui = tmp_path / "repo" / "tui"
    local = checkout_tui / "dist" / "index.js"
    local.parent.mkdir(parents=True)
    local.write_text("// local", encoding="utf-8")

    assert _build_tui(tmp_path / "repo", checkout_tui) == local
