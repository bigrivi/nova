from __future__ import annotations

import hashlib
import platform
import uuid


def _machine_id() -> str:
    try:
        return uuid.getnode().to_bytes(6, "big").hex()
    except Exception:
        return "unknown"


def fingerprint() -> str:
    raw = f"{_machine_id()}:{platform.node()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]
