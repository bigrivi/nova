from __future__ import annotations

import json
from pathlib import Path

import pytest

from nova.settings import Settings
from nova.skills.scanner import SkillParseError, load_skill_document
from nova.skills.service import SkillService, get_skill_service, initialize_skill_service
from nova.tools.edit import edit
from nova.tools.write import write


def _write_skill(
    skills_dir: Path,
    dir_name: str,
    *,
    name: str,
    description: str,
    compatibility: str = "",
    allowed_tools: str = "[read, bash]",
    extra_frontmatter: str = "",
    body: str = "# Skill\n\nDo work.\n",
) -> Path:
    skill_dir = skills_dir / dir_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]
    if compatibility:
        lines.append(f"compatibility: {compatibility}")
    lines.append(f"allowed-tools: {allowed_tools}")
    if extra_frontmatter:
        lines.extend(extra_frontmatter.splitlines())
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip("\n"))
    lines.append("")
    content = "\n".join(lines)
    path = skill_dir / "SKILL.md"
    path.write_text(content, encoding="utf-8")
    return path


def _settings_for_home(home: Path) -> Settings:
    return Settings(
        home=home,
        workspace_dir=home / "workspace",
        logs_dir=home / "logs",
        database_path=home / "nova.db",
        host="127.0.0.1",
        backend_port=8765,
        ui_port=8501,
        log_level="INFO",
        provider="ollama",
        model="gemma4:26b",
        ollama_base_url="http://localhost:11434",
        openai_base_url="https://api.openai.com/v1",
        openai_api_key="",
    )


def test_load_skill_document_parses_frontmatter_with_regex(tmp_path):
    skills_dir = tmp_path / "skills"
    skill_md_path = _write_skill(
        skills_dir,
        "code-review",
        name="code-review",
        description="Review code for bugs first.",
        compatibility="python>=3.11",
        allowed_tools='["read", "grep"]',
        extra_frontmatter="metadata:\n  author: ignored\n  version: ignored",
        body="# Code Review\n\nFocus on correctness.\n",
    )

    document = load_skill_document(skill_md_path, skills_dir=skills_dir)

    assert document.name == "code-review"
    assert document.description == "Review code for bugs first."
    assert document.compatibility == "python>=3.11"
    assert document.allowed_tools == ("read", "grep")
    assert document.body_content == "# Code Review\n\nFocus on correctness.\n"
    assert document.raw_content.startswith("---\nname: code-review\n")


def test_load_skill_document_requires_frontmatter_block(tmp_path):
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "invalid"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md_path = skill_dir / "SKILL.md"
    skill_md_path.write_text("# Missing frontmatter\n", encoding="utf-8")

    with pytest.raises(SkillParseError):
        load_skill_document(skill_md_path, skills_dir=skills_dir)


def test_skill_service_scans_valid_skills_only(tmp_path):
    skills_dir = tmp_path / "skills"
    _write_skill(skills_dir, "code-review", name="code-review", description="Review code.")
    (skills_dir / "missing-skill-md").mkdir(parents=True, exist_ok=True)
    bad_dir = skills_dir / "bad-frontmatter"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "SKILL.md").write_text("# nope\n", encoding="utf-8")

    service = SkillService(skills_dir)
    summaries = service.scan_skills()

    assert [summary.name for summary in summaries] == ["code-review"]
    assert summaries[0].description == "Review code."
    assert summaries[0].path == str((skills_dir / "code-review").resolve())


@pytest.mark.asyncio
async def test_write_tool_does_not_rescan_skill_catalog_automatically(tmp_path):
    home = tmp_path / "nova-home"
    settings = _settings_for_home(home)
    _write_skill(settings.skills_dir, "code-review", name="code-review", description="Review code.")
    initialize_skill_service(settings)

    service = get_skill_service()
    assert [skill.name for skill in service.list_skills()] == ["code-review"]

    result = await write(
        content="---\nname: incident\n"
        "description: Handle incidents.\n"
        "allowed-tools: [read]\n"
        "---\n\n# Incident\n\nRespond fast.\n",
        filePath=str(settings.skills_dir / "incident" / "SKILL.md"),
    )

    assert result.success is True
    assert [skill.name for skill in service.list_skills()] == ["code-review"]
    service.scan_skills()
    assert [skill.name for skill in service.list_skills()] == ["code-review", "incident"]


@pytest.mark.asyncio
async def test_edit_tool_does_not_rescan_skill_catalog_automatically(tmp_path):
    home = tmp_path / "nova-home"
    settings = _settings_for_home(home)
    skill_md_path = _write_skill(
        settings.skills_dir,
        "code-review",
        name="code-review",
        description="Review code.",
    )
    initialize_skill_service(settings)

    result = await edit(
        filePath=str(skill_md_path),
        oldString="description: Review code.",
        newString="description: Review code for bugs first.",
    )

    assert result.success is True
    service = get_skill_service()
    summaries = service.list_skills()
    assert summaries[0].description == "Review code."
    service.scan_skills()
    summaries = service.list_skills()
    assert summaries[0].description == "Review code for bugs first."
