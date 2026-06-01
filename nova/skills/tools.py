import json

from nova.llm import ToolResult
from nova.skills.service import SkillService
from nova.tools.registry import tool


class SkillTools:
    def __init__(self, skill_service: SkillService) -> None:
        self._skill_service = skill_service

    @tool(
        name="list_skills",
        description=(
            "List the skills currently available in Nova's in-memory skill catalog. "
            "Start here when the user asks to use a skill, asks what skills are available, mentions a likely skill name, "
            "or the task may match a reusable workflow. "
            "Use this before deciding whether to load or install a skill."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    async def list_skills(self) -> ToolResult:
        skills = self._skill_service.list_skills()
        if not skills:
            return ToolResult(success=True, content="No skills available.")

        lines = [f"Available skills ({len(skills)}):"]
        for skill in skills:
            lines.append(f"- name: {skill.name}")
            lines.append(f"  description: {skill.description or '(empty)'}")
            lines.append(f"  path: {skill.path}")
            if skill.compatibility:
                lines.append(f"  compatibility: {skill.compatibility}")
            allowed = ", ".join(skill.allowed_tools) if skill.allowed_tools else "(not specified)"
            lines.append(f"  allowed_tools: {allowed}")
        return ToolResult(success=True, content="\n".join(lines))

    @tool(
        name="load_skill",
        description=(
            "Load the full SKILL.md content for one skill from Nova's current in-memory skill catalog. "
            "Use this after you know the skill name and need the full instructions or examples. "
            "Prefer calling list_skills first if you have not confirmed the skill is available."
        ),
        parameters={
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Exact skill name to load. Prefer calling list_skills first if you are unsure.",
                }
            },
            "required": ["skill_name"],
        },
    )
    async def load_skill(self, skill_name: str) -> ToolResult:
        try:
            skill = self._skill_service.load_skill(skill_name)
        except KeyError:
            available_names = [
                item.name for item in self._skill_service.list_skills()]
            suggestion = ", ".join(
                available_names) if available_names else "(none)"
            return ToolResult(
                success=False,
                content=f"Skill not found: {skill_name}. Available skills: {suggestion}",
            )

        lines = [
            f"Skill loaded: {skill.name}",
            f"Path: {skill.path}",
            f"SKILL.md: {skill.skill_md_path}",
            f"Description: {skill.description or '(empty)'}",
        ]
        if skill.compatibility:
            lines.append(f"Compatibility: {skill.compatibility}")
        allowed = ", ".join(skill.allowed_tools) if skill.allowed_tools else "(not specified)"
        lines.append(f"Allowed tools: {allowed}")
        lines.append("")
        lines.append("Full SKILL.md:")
        lines.append(skill.raw_content)
        return ToolResult(success=True, content="\n".join(lines))

    @tool(
        name="install_skill",
        description=(
            "Install or update one skill from ClawHub into Nova's local runtime skills directory. "
            "Use this only when the user explicitly asks to install a skill. "
            "If you are unsure whether the skill is already installed locally, call `list_skills` first. "
            "If the skill already exists locally and the user did not ask to update or replace it, prefer `load_skill` instead of reinstalling. "
            "Returns install metadata only and does not include the full SKILL.md content. "
            "Accept either a ClawHub skill slug or a ClawHub skill page URL. "
            "Set force=true only when the user explicitly wants to replace or update an existing local skill directory."
        ),
        parameters={
            "type": "object",
            "properties": {
                "skill_ref": {
                    "type": "string",
                    "description": (
                        "ClawHub skill slug or full ClawHub skill page URL to install, "
                        "for example `review-skill` or `https://clawhub.ai/skills/team/review-skill`."
                    ),
                },
                "force": {
                    "type": "boolean",
                    "description": "Whether to replace an existing local skill directory with the same slug.",
                },
            },
            "required": ["skill_ref"],
        },
    )
    async def install_skill(self, skill_ref: str, force: bool = False) -> ToolResult:
        from nova.skills.installer import SkillInstallError
        try:
            result = await self._skill_service.install_from_clawhub(skill_ref, force=force)
        except SkillInstallError as exc:
            payload = {
                "status": "error",
                "error_code": exc.code,
                "message": str(exc),
                "skill_ref": skill_ref,
                "force": force,
                "skill_md_content_included": False,
            }
            if exc.next_action:
                payload["next_action"] = exc.next_action
            if exc.retry_after_seconds is not None:
                payload["retry_after_seconds"] = exc.retry_after_seconds
            return ToolResult(
                success=False,
                content=json.dumps(payload, ensure_ascii=False, indent=2),
                error=str(exc),
            )

        payload = {
            "status": "ok",
            "action": "updated" if result.replaced else "installed",
            "slug": result.slug,
            "skill_name": result.skill_name,
            "installed_path": result.installed_path,
            "skill_md_path": result.skill_md_path,
            "source_url": result.source_url,
            "catalog_refreshed": True,
            "skill_md_content_included": False,
            "next_action": "list_skills_or_load_skill",
        }
        return ToolResult(
            success=True,
            content=json.dumps(payload, ensure_ascii=False, indent=2),
        )
