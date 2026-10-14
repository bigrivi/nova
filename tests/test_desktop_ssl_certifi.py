"""The packaged desktop app must be able to verify TLS certificates.

The bug this pins: a frozen build ships certifi's CA bundle inside the app and
nothing tells OpenSSL to use it. CPython asks for its default CA paths, which in
a frozen interpreter point at the *build machine's* Python -- on the build host
that file exists, so nothing fails during the build, and on a user's machine it
does not, so every LLM call dies with ``CERTIFICATE_VERIFY_FAILED: unable to
get local issuer certificate``. It reproduces only in the packaged app, never in
a source checkout, which is why a smoke test that only checks "the app starts"
does not catch it.

Each spec has to wire the runtime hook in on its own, and getting that wrong on
one platform while fixing the other two is the obvious failure mode.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPECS = sorted(ROOT.glob("build_desktop_*.spec"))
HOOK = ROOT / "runtime_hook_ssl_certifi.py"


def test_there_are_specs_to_check() -> None:
    # Otherwise the loop below passes vacuously and a rename breaks the gate.
    assert len(SPECS) == 3, [p.name for p in SPECS]


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_spec_wires_the_ssl_runtime_hook(spec: Path) -> None:
    assert HOOK.is_file(), f"missing runtime hook: {HOOK}"
    assert "runtime_hook_ssl_certifi.py" in spec.read_text(encoding="utf-8"), (
        f"{spec.name} does not register the SSL runtime hook"
    )


def test_hook_points_openssl_at_an_existing_bundle() -> None:
    """Run the hook the way PyInstaller does, in a fresh interpreter."""
    probe = (
        "import os, certifi, runpy;"
        "runpy.run_path('runtime_hook_ssl_certifi.py');"
        "print(os.environ.get('SSL_CERT_FILE'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    configured = result.stdout.strip()
    assert configured, "hook left SSL_CERT_FILE unset"
    assert Path(configured).is_file(), configured


def test_hook_leaves_an_operator_override_alone() -> None:
    probe = (
        "import os, runpy;"
        "os.environ['SSL_CERT_FILE'] = '/tmp/operator-chose-this.pem';"
        "runpy.run_path('runtime_hook_ssl_certifi.py');"
        "print(os.environ.get('SSL_CERT_FILE'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "/tmp/operator-chose-this.pem"
