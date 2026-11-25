"""Compatibility alias for :mod:`novakit.llm.http_provider`."""

import sys

from novakit.llm import http_provider as _http_provider

sys.modules[__name__] = _http_provider
