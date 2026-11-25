"""Compatibility alias for :mod:`novakit.llm.reasoning`."""

import sys

from novakit.llm import reasoning as _reasoning

sys.modules[__name__] = _reasoning
