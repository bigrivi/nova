"""Scan runtime skill directories and parse SKILL.md frontmatter."""

from __future__ import annotations

import re
from pathlib import Path

from nova.skills.models import SkillDocument, SkillSummary

SKILL_FILE_NAME = "SKILL.md"
_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(?P<frontmatter>.*?)(?:\r?\n)---[ \t]*(?P<trailing>\r?\n|$)",
    re.DOTALL,
)
_KEY_VALUE_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9_-]*)\s*:\s*(?P<value>.+?)\s*$")


class SkillParseError(ValueError):
    """Raised when a skill package cannot be parsed safely."""


def _strip_quotes(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _parse_allowed_tools(value: str) -> tuple[str, ...]:
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if not text:
        return ()
    items = []
    for raw_item in text.split(","):
        item = _strip_quotes(raw_item).strip()
        if item:
            items.append(item)
    return tuple(items)


def _is_within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _parse_frontmatter(raw_content: str, fallback_name: str) -> tuple[dict[str, object], str]:
    match = _FRONTMATTER_RE.match(raw_content)
    if match is None:
        raise SkillParseError("SKILL.md must start with a frontmatter block delimited by ---")

    parsed: dict[str, object] = {
        "name": fallback_name,
        "description": "",
        "compatibility": "",
        "allowed_tools": (),
    }

    for line in match.group("frontmatter").splitlines():
        if not line.strip():
            continue
        if line[:1].isspace():
            continue
        kv_match = _KEY_VALUE_RE.match(line)
        if kv_match is None:
            continue
        key = kv_match.group("key").strip().lower()
        value = kv_match.group("value").strip()
        if key == "name":
            parsed["name"] = _strip_quotes(value) or fallback_name
        elif key == "description":
            parsed["description"] = _strip_quotes(value)
        elif key == "compatibility":
            parsed["compatibility"] = _strip_quotes(value)
        elif key == "allowed-tools":
            parsed["allowed_tools"] = _parse_allowed_tools(value)

    body_content = raw_content[match.end():].lstrip("\r\n")
    return parsed, body_content


def load_skill_document(skill_md_path: Path, skills_dir: Path) -> SkillDocument:
    skill_path = skill_md_path.resolve()
    root = skills_dir.resolve()
    if not _is_within(root, skill_path):
        raise SkillParseError(f"Skill file is outside skills directory: {skill_md_path}")
    if not skill_path.exists():
        raise SkillParseError(f"Skill file not found: {skill_md_path}")
    if skill_path.name != SKILL_FILE_NAME:
        raise SkillParseError(f"Unexpected skill file name: {skill_md_path}")

    raw_content = skill_path.read_text(encoding="utf-8", errors="replace")
    parsed, body_content = _parse_frontmatter(raw_content, fallback_name=skill_path.parent.name)
    return SkillDocument(
        name=str(parsed["name"]),
        description=str(parsed["description"]),
        path=str(skill_path.parent),
        skill_md_path=str(skill_path),
        compatibility=str(parsed["compatibility"]),
        allowed_tools=tuple(str(item) for item in parsed["allowed_tools"]),
        raw_content=raw_content,
        body_content=body_content,
        frontmatter=parsed,
    )


def scan_skills_dir(skills_dir: Path) -> list[SkillSummary]:
    root = skills_dir.resolve()
    summaries: list[SkillSummary] = []

    if not root.exists():
        return summaries

    seen_names: set[str] = set()
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if child.name.startswith(".") or not child.is_dir():
            continue

        skill_md_path = child / SKILL_FILE_NAME
        if not skill_md_path.is_file():
            continue

        try:
            document = load_skill_document(skill_md_path, skills_dir=root)
        except SkillParseError:
            continue

        key = document.name.lower()
        if key in seen_names:
            continue
        seen_names.add(key)
        summaries.append(
            SkillSummary(
                name=document.name,
                description=document.description,
                path=document.path,
                skill_md_path=document.skill_md_path,
                compatibility=document.compatibility,
                allowed_tools=document.allowed_tools,
            )
        )

    return summaries

