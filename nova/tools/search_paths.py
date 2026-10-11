"""A search result hands back a path the agent can use.

Every search tool reported absolute paths, because that is what ``rglob``
produced. That made the agent's next call depend on transcribing a
high-entropy string: one attempt of the eval suite spent four tool calls
reading ``/private/var/folders/kc/rtg...r2kh0000gn/...`` -- a path it had
mis-copied, one character short of the real one -- and then edited the
mistyped path, ending a turn on "Fixing it." with nothing fixed.

So a path is reported relative to the directory that was searched, which is
what ripgrep does and what ``read``'s own description already promised the
model would work. It is also shorter, which spends less of a context the
suite measures at 976K for good reason.
"""

from __future__ import annotations

from pathlib import Path


def _relative_to(root: Path, target: Path) -> str:
    """*target* as a path from *root*, or absolute when it is not under it.

    A search that reaches outside the searched directory keeps the absolute
    path, because there is nothing to be relative to -- and an agent that
    cannot act on a path it was just given is the bug this module exists to
    stop.
    """
    try:
        return str(target.relative_to(root))
    except ValueError:
        return str(target)
