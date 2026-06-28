from __future__ import annotations


_OPEN_TAG = "<memory-context>"
_CLOSE_TAG = "</memory-context>"
_OPEN_LOWER = _OPEN_TAG.lower()
_CLOSE_LOWER = _CLOSE_TAG.lower()


def _is_tag_prefix(text: str, tag: str) -> bool:
    tag_lower = tag.lower()
    text_lower = text.lower()
    n = len(text)
    for i in range(1, n + 1):
        if tag_lower.startswith(text_lower[:i]):
            return True
    return False


class StreamingContextScrubber:
    def __init__(self) -> None:
        self._in_span: bool = False
        self._buf: str = ""

    def reset(self) -> None:
        self._in_span = False
        self._buf = ""

    def feed(self, text: str) -> str:
        if not text:
            return ""
        buf = self._buf + text
        self._buf = ""
        out: list[str] = []

        while buf:
            if self._in_span:
                idx = buf.lower().find(_CLOSE_LOWER)
                if idx == -1:
                    # Check if we have a partial close tag at the end
                    for end in range(len(buf) - 1, max(len(buf) - len(_CLOSE_TAG) - 1, -1), -1):
                        if _is_tag_prefix(buf[end:], _CLOSE_TAG):
                            self._buf = buf[end:]
                            buf = ""
                            break
                    else:
                        buf = ""
                    continue
                buf = buf[idx + len(_CLOSE_TAG):]
                self._in_span = False
            else:
                idx = buf.lower().find(_OPEN_LOWER)
                if idx == -1:
                    # Check for partial open tag at end
                    for end in range(len(buf) - 1, max(len(buf) - len(_OPEN_TAG) - 1, -1), -1):
                        if _is_tag_prefix(buf[end:], _OPEN_TAG):
                            out.append(buf[:end])
                            self._buf = buf[end:]
                            buf = ""
                            break
                    else:
                        out.append(buf)
                        buf = ""
                else:
                    out.append(buf[:idx])
                    self._in_span = True
                    buf = buf[idx + len(_OPEN_TAG):]

        return "".join(out)

    def flush(self) -> str:
        if self._in_span:
            self._buf = ""
            self._in_span = False
            return ""
        tail = self._buf
        self._buf = ""
        return tail
