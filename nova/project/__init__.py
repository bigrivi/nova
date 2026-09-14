"""
Project grouping module.
"""

from .models import Project
from .paths import normalize_project_path, project_label_from_path
from .service import ProjectService, UNSET

__all__ = [
    "Project",
    "ProjectService",
    "UNSET",
    "normalize_project_path",
    "project_label_from_path",
]
