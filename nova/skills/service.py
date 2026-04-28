"""Runtime skill service and hooks."""

from __future__ import annotations

from pathlib import Path

from nova.settings import Settings, get_settings
from nova.skills.catalog import SkillCatalog
from nova.skills.installer import install_skill_from_clawhub
from nova.skills.models import SkillDocument, SkillSummary
from nova.skills.scanner import load_skill_document, scan_skills_dir


class SkillService:
    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir.expanduser().resolve()
        self.catalog = SkillCatalog()

    def scan_skills(self) -> list[SkillSummary]:
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        summaries = scan_skills_dir(self.skills_dir)
        self.catalog.replace(summaries)
        return self.catalog.list()

    def list_skills(self) -> list[SkillSummary]:
        return self.catalog.list()

    def load_skill(self, skill_name: str) -> SkillDocument:
        summary = self.catalog.get(skill_name)
        if summary is None:
            raise KeyError(skill_name)
        return load_skill_document(Path(summary.skill_md_path), skills_dir=self.skills_dir)

    async def install_from_clawhub(self, skill_ref: str, *, force: bool = False):
        result = await install_skill_from_clawhub(
            skill_ref,
            skills_dir=self.skills_dir,
            force=force,
        )
        self.scan_skills()
        return result


_skill_service: SkillService | None = None


def initialize_skill_service(settings: Settings | None = None) -> SkillService:
    global _skill_service
    settings = settings or get_settings()
    skills_dir = settings.skills_dir.resolve()
    if _skill_service is None or _skill_service.skills_dir != skills_dir:
        _skill_service = SkillService(skills_dir=skills_dir)
    _skill_service.scan_skills()
    return _skill_service


def get_skill_service() -> SkillService:
    global _skill_service
    if _skill_service is None:
        return initialize_skill_service()
    return _skill_service
def reset_skill_service() -> None:
    global _skill_service
    _skill_service = None
