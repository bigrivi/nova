"""Compatibility alias for :mod:`novakit.llm.faker`."""

import sys

from novakit.llm import faker as _faker

sys.modules[__name__] = _faker
