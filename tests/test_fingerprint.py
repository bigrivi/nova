import hashlib
import sys
from unittest import mock

import nova.license.fingerprint as fp


def test_darwin_uses_io_platform_uuid(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(fp, "_io_platform_uuid", lambda: "UUID-X")
    assert fp._stable_machine_id() == "UUID-X"


def test_win32_keeps_mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(fp, "_machine_id", lambda: "deadbeef00ff")
    assert fp._stable_machine_id() == "deadbeef00ff"


def test_linux_uses_machine_id(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(fp, "_read_machine_id", lambda: "machid123")
    assert fp._stable_machine_id() == "machid123"


def test_fallback_to_mac_when_primary_empty(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(fp, "_read_machine_id", lambda: "")
    monkeypatch.setattr(fp, "_machine_id", lambda: "aa00bb11cc22")
    assert fp._stable_machine_id() == "aa00bb11cc22"


def test_io_platform_uuid_parser(monkeypatch):
    monkeypatch.setattr(
        fp.subprocess,
        "run",
        lambda *a, **kw: mock.Mock(
            stdout='  "IOPlatformUUID" = "ABC-123"\n  "IOPlatformSerialNumber" = "X"\n'
        ),
    )
    assert fp._io_platform_uuid() == "ABC-123"

    def boom(*a, **kw):
        raise FileNotFoundError

    monkeypatch.setattr(fp.subprocess, "run", boom)
    assert fp._io_platform_uuid() == ""


def test_fingerprint_format(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(fp, "_io_platform_uuid", lambda: "ABC")
    assert fp.fingerprint() == hashlib.sha256(b"ABC").hexdigest()[:24]