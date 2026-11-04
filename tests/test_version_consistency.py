"""One version string, checked in the places it is written down twice.

``nova/version.py`` is the source (re-exported as ``nova.__version__``): packaging reads it dynamically
(``[tool.setuptools.dynamic]``), the CLI and ``/health`` report it, and the
release workflow refuses a tag whose name disagrees with it. The only copies are
four doc examples — and a bump that misses one leaves the docs telling users a
version that cannot be installed, which no test catches today.
"""

from __future__ import annotations

import pathlib
import re

import pytest

import nova

VERSION = nova.__version__
ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Each doc states the release version once; the pattern is the sentence around
#: it, so a reworded page fails loudly instead of silently going unchecked.
DOC_REFERENCES = {
    "docs/getting-started/installation.md": (
        r"install a specific release tag \(e\.g\. (\d+\.\d+\.\d+)\)"
    ),
    "docs/zh-CN/getting-started/installation.md": (
        r"安装指定的发布 tag（例如 (\d+\.\d+\.\d+)）"
    ),
    "docs/tui/index.md": r"# nova (\d+\.\d+\.\d+)",
    "docs/zh-CN/tui/index.md": r"# nova (\d+\.\d+\.\d+)",
}


def test_the_version_is_a_plain_release_number():
    """The release workflow compares it to a tag, so it has to look like one."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION), VERSION


def test_packaging_reads_the_version_instead_of_declaring_one():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'dynamic = ["version"]' in pyproject
    assert 'version = { attr = "nova.__version__" }' in pyproject
    assert not re.search('^version\\s*=\\s*"', pyproject, re.MULTILINE), (
        "a literal version in pyproject would win over nova.__version__"
    )


@pytest.mark.parametrize(("relative_path", "pattern"), sorted(DOC_REFERENCES.items()))
def test_each_doc_quotes_the_current_version(relative_path, pattern):
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    found = re.search(pattern, text)

    assert found, f"{relative_path} no longer states the version; update the pattern"
    assert found.group(1) == VERSION, f"{relative_path} says {found.group(1)}"


def test_the_release_version_appears_only_once_in_the_source():
    """A hardcoded copy beside the constant would drift without a failure."""
    offenders = []
    for path in (ROOT / "nova").rglob("*.py"):
        relative = path.relative_to(ROOT)
        if relative == pathlib.Path("nova/version.py"):
            continue
        for match in re.finditer(r'"(\d+\.\d+\.\d+)"', path.read_text(encoding="utf-8")):
            offenders.append(f"{relative}: {match.group(1)}")

    assert not offenders, offenders
