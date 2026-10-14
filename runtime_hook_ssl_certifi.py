"""PyInstaller runtime hook: point OpenSSL at certifi's CA bundle.

A frozen build has no working trust store out of the box. CPython asks OpenSSL
for its default CA paths, which in a frozen interpreter still point at the
*build machine's* Python -- on macOS that is
``/Library/Frameworks/Python.framework/Versions/3.12/etc/openssl/cert.pem``,
a file that does not exist on the machine running the app. The context comes
back with no trusted CAs and every TLS handshake fails with
``CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate``.

PyInstaller's own ``hook-certifi.py`` only collects ``cacert.pem`` as a data
file; it never tells OpenSSL where it is. The bundle is shipped and simply
unused, which is why this fails only in the packaged app and never in a source
checkout.

Setting ``SSL_CERT_FILE`` is enough: CPython reads it when
``ssl.create_default_context()`` builds a context, and that is what aiohttp and
httpx both go through. The other two names are for anything shelling out to
curl. ``setdefault`` leaves an operator-provided override in place.

Runs before the entry script, so this is in place before any connection is
attempted.
"""

import os


def _point_openssl_at_certifi() -> None:
    try:
        import certifi
    except ImportError:
        return

    bundle = certifi.where()
    if not bundle or not os.path.isfile(bundle):
        return

    for variable in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        os.environ.setdefault(variable, bundle)


_point_openssl_at_certifi()
