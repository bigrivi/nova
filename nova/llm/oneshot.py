"""Compatibility alias for :mod:`novakit.llm.oneshot`."""

import sys

from novakit.llm import oneshot as _oneshot

sys.modules[__name__] = _oneshot
