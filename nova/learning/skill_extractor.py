"""Review-driven skill extraction and self-improvement.

Modelled on Hermes's background review: after a turn the model is asked
whether anything is worth persisting, and is steered to update an existing
skill rather than add a new one. The turn's tool-call count only decides
whether the review is worth paying for -- it never forces a write.
"""

from __future__ import annotations

import json
import logging
import re
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
    return re.sub(r"^version:\s*\d+\s*", "", content, flags=re.MULTILINE).lstrip()


@dataclass
class TurnContext:
    session_id: str
    messages: list[dict]
    tool_call_count: int
    user_id: str = ""


@dataclass
class SkillProposal:
    action: str  # "create" | "update"
    name: str
    content: str
    references: dict[str, str] | None = None


_REVIEW_PROMPT = """\
Review the conversation above and update the skill library.

A no-op is a legitimate result: if nothing generalizable happened, reply
{{"action": "none"}}.

Signals that warrant action:
- the user corrected your style, workflow, or sequence of steps;
- a non-trivial technique, fix, workaround, or debugging path emerged;
- a skill used this session turned out to be wrong or missing a step.

Prefer, in order:
1. UPDATE an existing skill that covers this territory.
2. ADD a reference file under an existing umbrella skill.
3. CREATE a new class-level skill only when nothing existing fits.

Keep the library class-level: one broad skill with a few references, not a
flat list of one-task skills.

Existing skills:
{existing}

Reply with ONLY JSON:
- no-op: {{"action": "none"}}
- update: {{"action": "update", "name": "<existing name>", "content": "<full revised SKILL.md>"}}
- create: {{"action": "create", "name": "<kebab-case>", "content": "<full SKILL.md>", "references": {{"<topic>.md": "<content>"}}}}

Example: {{"action": "update", "name": "csv-analysis", "content": "# CSV Analysis\\n..."}}

Conversation:
{transcript}
"""


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
        prompt = _REVIEW_PROMPT.format(
            existing=self._existing_summary(), transcript=transcript
        )
        try:
            raw = await self._complete(prompt, turn.session_id)
            proposal = _parse_json(raw)
        except Exception as e:
            log.warning("skill review failed: %s", e)
            return None
        if not proposal or not isinstance(proposal, dict):
            log.warning("skill review returned unparsable output: %r", raw[:300])
            return None
        action = proposal.get("action")
        log.info("skill review action=%s name=%s", action, proposal.get("name"))
        if action == "none":
            return None
        name = (proposal.get("name") or "").strip()
        content = proposal.get("content") or ""
        if not name or not content:
            return None

        if action == "create":
            # A colliding name is an update, never a second skill.
            resolved = self._find_similar(name, content)
            if resolved is not None:
                action, name = "update", resolved
            elif (self.skills_dir / name / "SKILL.md").exists():
                action = "update"

        skill_dir = self.skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"
        if action == "update" or skill_path.exists():
            existing = skill_path.read_text(encoding="utf-8") if skill_path.exists() else ""
            if existing and _jaccard(
                _tokens(_strip_version(content)[:400]),
                _tokens(_strip_version(existing)[:400]),
            ) >= 0.85:
                return None  # nothing new to record
            if existing:
                self._write_revision(skill_path, content)
            else:
                skill_path.write_text(f"version: 1\n\n{content.strip()}\n", encoding="utf-8")
        else:
            skill_path.write_text(f"version: 1\n\n{content.strip()}\n", encoding="utf-8")

        references = proposal.get("references")
        if isinstance(references, dict):
            self._write_references(skill_dir, references)

        return SkillProposal(
            action="update" if action == "update" else "create",
            name=name,
            content=content,
            references=references if isinstance(references, dict) else None,
        )

    async def _complete(self, prompt: str, session_id: str) -> str:
        chunks: list[str] = []
        final = ""
        async for ev in self.llm.chat_stream(
            [{"role": "user", "content": prompt}],
            model=self.model or "gpt-4o",
            session_id=session_id,
            reasoning_effort="high",
        ):
            if type(ev).__name__ == "TextDelta" and getattr(ev, "content", None):
                chunks.append(ev.content)
            if type(ev).__name__ == "Done":
                final = getattr(ev, "content", "") or ""
                break
            if type(ev).__name__ == "Error":
                raise RuntimeError(getattr(ev, "message", "stream error"))
        return "".join(chunks) or final

    def _existing_summary(self) -> str:
        """Name plus first line of each installed skill, for the review prompt."""
        if not self.skills_dir.exists():
            return "- (none)"
        lines = []
        for path in sorted(self.skills_dir.iterdir()):
            skill_md = path / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                body = skill_md.read_text(encoding="utf-8")
            except OSError:
                continue
            description = next(
                (line.strip("# ").strip() for line in _strip_version(body).splitlines() if line.strip()),
                "",
            )
            lines.append(f"- {path.name}: {description[:120]}")
        return "\n".join(lines) if lines else "- (none)"

    def _find_similar(self, name: str, content: str) -> str | None:
        """Return an existing skill that overlaps the proposed one, if any.

        Names alone are unreliable -- the model names the same workflow
        differently each run -- so content is a second signal. Either
        crossing ``_SIMILARITY_THRESHOLD`` is enough to merge.
        """
        if not self.skills_dir.exists():
            return None
        existing = [p for p in self.skills_dir.iterdir() if (p / "SKILL.md").exists()]
        if not existing:
            return None
        name_tokens = _tokens(name)
        content_tokens = _tokens(content[:400])
        best, best_score = None, 0.0
        for cand in existing:
            score = _jaccard(name_tokens, _tokens(cand.name))
            try:
                cand_content = (cand / "SKILL.md").read_text(encoding="utf-8")[:400]
            except OSError:
                cand_content = ""
            score = max(score, _jaccard(content_tokens, _tokens(cand_content)))
            if score > best_score:
                best, best_score = cand.name, score
        if best is not None and best_score >= 0.35:
            return best
        return None

    def _write_references(self, skill_dir: Path, references: dict) -> None:
        ref_dir = skill_dir / "references"
        ref_dir.mkdir(parents=True, exist_ok=True)
        for topic, body in references.items():
            if not isinstance(topic, str) or not isinstance(body, str):
                continue
            safe = topic.replace("/", "_").replace("\\", "_")
            (ref_dir / safe).write_text(body, encoding="utf-8")

    def _write_revision(self, skill_path: Path, content: str) -> None:
        previous = skill_path.read_text(encoding="utf-8")
        skill_path.write_text(self._with_version(content, previous), encoding="utf-8")

    async def improve(self, skill_name: str, correction: str, session_id: str = "") -> None:
        skill_path = self.skills_dir / skill_name / "SKILL.md"
        if not skill_path.exists():
            return
        try:
            current = skill_path.read_text(encoding="utf-8")
            if self.llm is None:
                return
            revised = await self._complete(
                f"Revise this skill based on correction: {correction}\n\n{current}",
                session_id or skill_name,
            )
            if revised.strip():
                skill_path.write_text(self._with_version(revised, current), encoding="utf-8")
        except Exception as e:
            log.warning("skill improvement failed: %s", e)

    @staticmethod
    def _with_version(content: str, previous: str) -> str:
        """Stamp a revision marker, bumping the version when there was one."""
        old = re.search(r"^version:\s*(\d+)\s*$", previous, re.MULTILINE)
        version = (int(old.group(1)) + 1) if old else 2
        body = re.sub(r"^version:\s*\d+\s*\n?", "", content).strip()
        return f"version: {version}\n\n{body}\n"


def _parse_json(raw: str) -> dict | None:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        return None
