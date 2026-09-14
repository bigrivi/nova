from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Project:
    """A named grouping for sessions.

    ``path`` is the directory the project's sessions run in by default. It is
    optional (a project can exist without a folder) and is not unique: two
    projects may point at the same directory.
    """

    id: str
    name: str
    path: Optional[str] = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at: int = field(default_factory=lambda: int(time.time() * 1000))
