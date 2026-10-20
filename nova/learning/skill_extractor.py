"""Skill extraction and self-improvement from completed turns."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


def _tokens(text: str) -> set[str]:
    """Lower-case word tokens split on whitespace, underscores, slashes and dashes."""
    normalized = text.lower()
    for sep in ("_", "/", "-"):
        normalized = normalized.replace(sep, " ")
    return {part for part in normalized.split() if part}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _strip_version(content: str) -> str:
    """Drop the ``version: N`` marker so revisions compare on their body."""
    import re

    return re.sub(r"^version:\s*\d+\s*", "", content, flags=re.MULTILINE).lstrip()


@dataclass
class TurnContext:
    session_id: str
    messages: list[dict]
    tool_call_count: int
    user_id: str = ""


@dataclass
class SkillProposal:
    name: str
    content: str
    revision: str = ""


class SkillExtractor:
    def __init__(self, skills_dir: Path, min_tool_calls: int = 4, llm=None, model: str = ""):
        self.skills_dir = Path(skills_dir)
        self.min_tool_calls = min_tool_calls
        self.llm = llm
        self.model = model

    async def maybe_extract(self, turn: TurnContext) -> SkillProposal | None:
        if turn.tool_call_count < self.min_tool_calls:
            return None
        if self.llm is None:
            return None
        transcript = "\n".join(
            f"{m.get('role', '')}: {m.get('content', '')}" for m in turn.messages
        )
        existing = self._existing_names()
        existing_hint = (
            "Existing skills: " + ", ".join(existing) + ". "
            "If this work is the same skill as one of them, return that exact "
            "name and the full revised content (it will be merged). "
            "Otherwise return a new kebab-case name. "
            if existing
            else ""
        )
        try:
            chunks = []
            final_content = ""
            async for ev in self.llm.chat_stream(
                [{"role": "user", "content":
                  "Extract a reusable skill from this transcript. "
                  + existing_hint +
                  "Reply with ONLY a JSON object, no markdown, with keys 'name' (kebab-case) "
                  "and 'content' (the full skill markdown). Example: "
                  '{"name": "csv-sales", "content": "# CSV Sales\\nSteps..."}\n\n' + transcript}],
                model=self.model or "gpt-4o",
                session_id=turn.session_id,
                reasoning_effort="high",
            ):
                if type(ev).__name__ == "TextDelta" and getattr(ev, "content", None):
                    chunks.append(ev.content)
                if type(ev).__name__ == "Done":
                    final_content = getattr(ev, "content", "") or ""
                    break
                if type(ev).__name__ == "Error":
                    raise RuntimeError(getattr(ev, "message", "stream error"))
            raw = ("".join(chunks) or final_content).strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.lower().startswith("json"):
                    raw = raw[4:].strip()
            import json
            try:
                proposal = json.loads(raw)
            except json.JSONDecodeError:
                # Fallback: try to find a JSON object in the text
                import re
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    proposal = json.loads(m.group(0))
                else:
                    raise
        except Exception as e:
            log.warning("skill extraction failed: %s", e)
            return None
        if not proposal or not isinstance(proposal, dict):
            return None
        name = proposal.get("name")
        content = proposal.get("content")
        if not name or not content:
            return None
        # Reuse an existing skill when it overlaps strongly, to avoid skill
        # proliferation from slightly different LLM-chosen names. An almost
        # identical proposal is a no-op: rewriting it only bumps the version.
        similar = self._find_similar(name, content)
        if similar is not None:
            existing = (self.skills_dir / similar / "SKILL.md").read_text(
                encoding="utf-8"
            )
            if (
                _jaccard(
                    _tokens(_strip_version(content)[:400]),
                    _tokens(_strip_version(existing)[:400]),
                )
                >= 0.85
            ):
                return None
            name = similar
        skill_dir = self.skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"
        if skill_path.exists():
            # Same skill, new turn: revise it rather than adding a near-duplicate.
            self._write_revision(skill_path, content)
        else:
            skill_path.write_text(
                f"version: 1\n\n{content.strip()}\n", encoding="utf-8"
            )
        return SkillProposal(
            name=name, content=content, revision=proposal.get("revision", "")
        )

    def _existing_names(self) -> list[str]:
        """Names of the skills already installed, for reuse by the extractor."""
        if not self.skills_dir.exists():
            return []
        return sorted(
            p.name for p in self.skills_dir.iterdir() if (p / "SKILL.md").exists()
        )

    def _find_similar(self, name: str, content: str = "") -> str | None:
        """Return an existing skill that overlaps the proposed one, if any.

        Two signals, because names alone are unreliable: the LLM gives the
        same workflow a different name each time, while the body keeps the
        same vocabulary. Name tokens and the first 400 characters of content
        are each compared with Jaccard similarity; either signal crossing
        ``_SIMILARITY_THRESHOLD`` is enough to merge.
        """
        if not self.skills_dir.exists():
            return None
        existing = [p for p in self.skills_dir.iterdir() if (p / "SKILL.md").exists()]
        if not existing:
            return None
        name_tokens = _tokens(name)
        content_tokens = _tokens(content[:400])
        best = None
        best_score = 0.0
        for cand in existing:
            cand_tokens = _tokens(cand.name)
            score = _jaccard(name_tokens, cand_tokens)
            try:
                cand_content = (cand / "SKILL.md").read_text(encoding="utf-8")[:400]
            except OSError:
                cand_content = ""
            content_score = _jaccard(content_tokens, _tokens(cand_content))
            score = max(score, content_score)
            if score > best_score:
                best_score = score
                best = cand.name
        if best is not None and best_score >= self._SIMILARITY_THRESHOLD:
            return best
        return None

    #: Jaccard threshold above which a proposal is treated as the same skill.
    #: Below it, two data tasks may share words ("csv") without being one skill.
    _SIMILARITY_THRESHOLD = 0.35

    def _write_revision(self, skill_path: Path, content: str) -> None:
        """Replace a skill's body, bumping its version marker."""
        previous = skill_path.read_text(encoding="utf-8")
        skill_path.write_text(
            self._with_version(content, previous), encoding="utf-8"
        )

    async def improve(self, skill_name: str, correction: str, session_id: str = "") -> None:
        skill_path = self.skills_dir / skill_name / "SKILL.md"
        if not skill_path.exists():
            return
        try:
            current = skill_path.read_text(encoding="utf-8")
            if self.llm is None:
                return
            chunks = []
            final = ""
            async for ev in self.llm.chat_stream(
                [{"role": "user", "content": f"Revise this skill based on correction: {correction}\n\n{current}"}],
                model=self.model or "gpt-4o",
                session_id=session_id or skill_name,
                reasoning_effort="high",
            ):
                if type(ev).__name__ == "TextDelta" and getattr(ev, "content", None):
                    chunks.append(ev.content)
                if type(ev).__name__ == "Done":
                    final = getattr(ev, "content", "") or ""
                    break
                if type(ev).__name__ == "Error":
                    raise RuntimeError(getattr(ev, "message", "stream error"))
            revised = ("".join(chunks) or final).strip()
            if not revised:
                return
            skill_path.write_text(self._with_version(revised, current), encoding="utf-8")
        except Exception as e:
            log.warning("skill improvement failed: %s", e)

    @staticmethod
    def _with_version(content: str, previous: str) -> str:
        """Stamp a revision marker, bumping the version when there was one.

        The marker is what makes an improvement visible: a skill whose file is
        rewritten in place looks unchanged to anyone reading it later, so the
        version is the only record that the skill was revised.
        """
        import re

        old = re.search(r"^version:\s*(\d+)\s*$", previous, re.MULTILINE)
        version = (int(old.group(1)) + 1) if old else 2
        body = re.sub(r"^version:\s*\d+\s*\n?", "", content).strip()
        return f"version: {version}\n\n{body}\n"
