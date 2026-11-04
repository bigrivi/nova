"""A release cannot be tagged without written notes.

The release workflow publishes `release_notes/<tag>.md` as the release body, and
refuses to upload anything when the file is missing. That guard lives in CI, far
from the moment a version is bumped, so this test states the same requirement
where the bump happens: `nova.__version__` and `release_notes/v<version>.md` move
together.
"""

from __future__ import annotations

import pathlib

import nova

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOTES = ROOT / "release_notes"


def test_the_current_version_has_written_release_notes():
    path = NOTES / f"v{nova.__version__}.md"

    assert path.exists(), f"write {path.relative_to(ROOT)} before tagging"
    assert path.stat().st_size > 0, f"{path.relative_to(ROOT)} is empty"


def test_the_notes_state_the_version_they_describe():
    """A file copied from the previous release is the obvious mistake."""
    path = NOTES / f"v{nova.__version__}.md"
    first_line = path.read_text(encoding="utf-8").splitlines()[0]

    assert first_line.strip() == f"# Nova {nova.__version__}", first_line


def test_every_recorded_release_has_a_heading():
    """Historical notes stay in the tree; a bad copy shows up here, not in a diff."""
    for path in sorted(NOTES.glob("v*.md")):
        version = path.stem.removeprefix("v")
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        assert first_line.strip() == f"# Nova {version}", f"{path.name}: {first_line}"
