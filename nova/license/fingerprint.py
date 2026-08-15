from __future__ import annotations

import hashlib
import subprocess
import sys
import uuid


def _io_platform_uuid() -> str:
    try:
        out = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in out.splitlines():
        line = line.strip()
        if line.startswith('"IOPlatformUUID"') and "=" in line:
            value = line.split("=", 1)[1].strip().strip('"')
            if value:
                return value
    return ""


def _read_machine_id() -> str:
    try:
        raw = open("/etc/machine-id", encoding="utf-8").read().strip()
    except OSError:
        return ""
    return raw


def _machine_id() -> str:
    """MAC-address fallback; also the stable machine id on Windows."""
    try:
        return uuid.getnode().to_bytes(6, "big").hex()
    except Exception:
        return "unknown"


def _stable_machine_id() -> str:
    if sys.platform == "darwin":
        machine_id = _io_platform_uuid()
    elif sys.platform == "win32":
        machine_id = _machine_id()
    else:
        machine_id = _read_machine_id()
    if not machine_id or machine_id == "unknown":
        machine_id = _machine_id()
    return machine_id


def fingerprint() -> str:
    return hashlib.sha256(_stable_machine_id().encode()).hexdigest()[:24]