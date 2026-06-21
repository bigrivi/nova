from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from nova.license.crypto import verify_signature
from nova.license.fingerprint import fingerprint


class LicenseStatus:
    VALID = "valid"
    EXPIRED = "expired"
    INVALID_SIGNATURE = "invalid_signature"
    WRONG_MACHINE = "wrong_machine"
    NOT_FOUND = "not_found"
    MALFORMED = "malformed"

    def __init__(self, status: str, message: str = "") -> None:
        self.status = status
        self.message = message

    @property
    def is_valid(self) -> bool:
        return self.status == self.VALID


LAST_CHECK_FILE = "last_check"


def _license_path() -> Path:
    home = Path(os.environ.get("NOVA_HOME", Path.home() / ".nova"))
    return home / "license.lic"


def _last_check_path() -> Path:
    home = Path(os.environ.get("NOVA_HOME", Path.home() / ".nova"))
    return home / LAST_CHECK_FILE


def _read_last_check() -> Optional[float]:
    path = _last_check_path()
    if not path.exists():
        return None
    try:
        raw = path.read_text().strip()
        return float(raw)
    except (ValueError, OSError):
        return None


def _write_last_check(timestamp: float) -> None:
    path = _last_check_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(timestamp))


def validate() -> LicenseStatus:
    lic_path = _license_path()
    if not lic_path.exists():
        return LicenseStatus(LicenseStatus.NOT_FOUND, "License file not found")

    try:
        payload = json.loads(lic_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return LicenseStatus(LicenseStatus.MALFORMED, str(exc))

    for key in ("fingerprint", "expires", "signature"):
        if key not in payload:
            return LicenseStatus(LicenseStatus.MALFORMED, f"Missing field: {key}")

    sig = bytes.fromhex(payload["signature"])
    data = json.dumps({k: v for k, v in payload.items() if k != "signature"}, sort_keys=True).encode()

    if not verify_signature(data, sig):
        return LicenseStatus(LicenseStatus.INVALID_SIGNATURE, "Signature verification failed")

    if payload["fingerprint"] != fingerprint():
        return LicenseStatus(LicenseStatus.WRONG_MACHINE, "License is not for this machine")

    try:
        expires = float(payload["expires"])
    except (ValueError, TypeError):
        return LicenseStatus(LicenseStatus.MALFORMED, "Invalid expires field")

    now = time.time()

    last_check = _read_last_check()
    if last_check is not None and now < last_check - 60:
        return LicenseStatus(LicenseStatus.EXPIRED, "System clock appears to have been tampered with")

    if now > expires:
        return LicenseStatus(LicenseStatus.EXPIRED, "License has expired")

    _write_last_check(now)
    return LicenseStatus(LicenseStatus.VALID)
