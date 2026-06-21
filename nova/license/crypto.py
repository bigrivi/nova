from __future__ import annotations

from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAZycNlDirsOJnF7UyX6SoiPfoRQ53qJIEaMkvwihpH9k=
-----END PUBLIC KEY-----"""


def load_public_key() -> Ed25519PublicKey:
    return load_pem_public_key(PUBLIC_KEY_PEM)  # type: ignore[return-value]


def verify_signature(data: bytes, signature: bytes) -> bool:
    try:
        pk = load_public_key()
        pk.verify(signature, data)
        return True
    except Exception:
        return False


def sign(data: bytes, private_key_pem: bytes) -> bytes:
    pk = load_pem_private_key(private_key_pem, password=None)
    assert isinstance(pk, Ed25519PrivateKey)
    return pk.sign(data)
