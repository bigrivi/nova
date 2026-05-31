"""Runtime skill service and hooks."""

from __future__ import annotations

from pathlib import Path

from nova.skills.catalog import SkillCatalog
from nova.skills.installer import install_skill_from_clawhub
from nova.skills.models import SkillDocument, SkillSummary
from nova.skills.scanner import load_skill_document, scan_skills_dir


def _is_within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class SkillService:
    def __init__(self, skills_dir: Path, fallback_dir: Path | None = None) -> None:
        self.skills_dir = skills_dir.expanduser().resolve()
        self.fallback_dir = fallback_dir.expanduser().resolve() if fallback_dir else None
        self.catalog = SkillCatalog()

    def _scan_one(self, directory: Path) -> list[SkillSummary]:
        if directory == self.skills_dir:
            directory.mkdir(parents=True, exist_ok=True)
        return scan_skills_dir(directory)

    def scan_skills(self) -> list[SkillSummary]:
        summaries = self._scan_one(self.skills_dir)
        if self.fallback_dir:
            fallback = self._scan_one(self.fallback_dir)
            existing = {s.name.lower() for s in summaries}
            summaries.extend(s for s in fallback if s.name.lower() not in existing)
        self.catalog.replace(summaries)
        return self.catalog.list()

    def list_skills(self) -> list[SkillSummary]:
        return self.catalog.list()

    def load_skill(self, skill_name: str) -> SkillDocument:
        summary = self.catalog.get(skill_name)
        if summary is None:
            raise KeyError(skill_name)
        skill_path = Path(summary.skill_md_path)
        if self.fallback_dir and not _is_within(self.skills_dir, skill_path):
            skills_dir = self.fallback_dir
        else:
            skills_dir = self.skills_dir
        return load_skill_document(skill_path, skills_dir=skills_dir)

    async def install_from_clawhub(self, skill_ref: str, *, force: bool = False):
        result = await install_skill_from_clawhub(
            skill_ref,
            skills_dir=self.skills_dir,
            force=force,
        )
        self.scan_skills()
        return result

    async def install_global(self, skill_ref: str, *, force: bool = False):
        target = self.fallback_dir or self.skills_dir
        result = await install_skill_from_clawhub(
            skill_ref,
            skills_dir=target,
            force=force,
        )
        self.scan_skills()
        return result
