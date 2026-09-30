from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Project:
    """A named grouping for sessions.

    ``path`` is the directory the project's sessions run in by default. It is
    optional (a project can exist without a folder) and is not unique: two
    projects may point at the same directory.
    """

    id: str
    name: str
    path: str | None = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at: int = field(default_factory=lambda: int(time.time() * 1000))
