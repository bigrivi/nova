"""
Project grouping module.
"""

from .models import Project
from .paths import normalize_project_path, project_label_from_path
from .service import UNSET, ProjectService

__all__ = [
    "UNSET",
    "Project",
    "ProjectService",
    "normalize_project_path",
    "project_label_from_path",
]
