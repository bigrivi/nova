#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nova.license.crypto import sign


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate a Nova license file")
    parser.add_argument("--fingerprint", required=True, help="Machine fingerprint")
    parser.add_argument("--expires", required=True, help="Expiration date (Unix timestamp or ISO 8601)")
    parser.add_argument("--user", default="", help="User identifier (optional)")
    parser.add_argument("--private-key", default=str(ROOT / "tools" / "license_private.pem"), help="Path to Ed25519 private key")
    parser.add_argument("-o", "--output", default="license.lic", help="Output path")

    args = parser.parse_args()

    try:
        expires = float(args.expires)
    except ValueError:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(args.expires)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        expires = dt.timestamp()

    payload = {
        "fingerprint": args.fingerprint,
        "expires": expires,
        "issued": __import__("time").time(),
        "user": args.user,
    }

    data = json.dumps(payload, sort_keys=True).encode()
    private_key_pem = Path(args.private_key).read_bytes()
    payload["signature"] = sign(data, private_key_pem).hex()

    output = Path(args.output)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"License generated: {output.resolve()}")


if __name__ == "__main__":
    main()
