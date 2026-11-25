"""Compatibility alias for :mod:`novakit.llm.provider`."""

import sys

from novakit.llm import provider as _provider

sys.modules[__name__] = _provider
