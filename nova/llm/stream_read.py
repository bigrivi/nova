"""Compatibility alias for :mod:`novakit.llm.stream_read`."""

import sys

from novakit.llm import stream_read as _stream_read

sys.modules[__name__] = _stream_read
