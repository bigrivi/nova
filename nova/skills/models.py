"""Skill models shared by scanner, catalog, and tools."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SkillSummary:
    name: str
    description: str
    path: str
    skill_md_path: str
    compatibility: str = ""
    allowed_tools: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SkillDocument:
    name: str
    description: str
    path: str
    skill_md_path: str
    compatibility: str
    allowed_tools: tuple[str, ...]
    raw_content: str
    body_content: str
    frontmatter: dict[str, object]


@dataclass(frozen=True)
class SkillInstallResult:
    slug: str
    skill_name: str
    installed_path: str
    skill_md_path: str
    source_url: str
    replaced: bool = False
