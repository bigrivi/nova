"""Compatibility alias for :mod:`novakit.llm.images`."""

import sys

from novakit.llm import images as _images

sys.modules[__name__] = _images
