"""Compatibility alias for :mod:`novakit.llm.stream_trace`."""

import sys

from novakit.llm import stream_trace as _stream_trace

sys.modules[__name__] = _stream_trace
