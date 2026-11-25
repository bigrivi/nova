"""Compatibility alias for :mod:`novakit.llm.policy`."""

import sys

from novakit.llm import policy as _policy

sys.modules[__name__] = _policy
