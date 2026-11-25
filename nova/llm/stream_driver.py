"""Compatibility alias for :mod:`novakit.llm.stream_driver`."""

import sys

from novakit.llm import stream_driver as _stream_driver

sys.modules[__name__] = _stream_driver
