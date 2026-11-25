"""Compatibility alias for :mod:`novakit.llm.accumulator`."""

import sys

from novakit.llm import accumulator as _accumulator

sys.modules[__name__] = _accumulator
