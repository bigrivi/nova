"""Compatibility alias for :mod:`novakit.llm.framing`."""

import sys

from novakit.llm import framing as _framing

sys.modules[__name__] = _framing
