"""An LLM second opinion on commands the rules flagged.

The rules are a blunt instrument: they match on shape, so a rule written for
`curl ... | bash` also catches an agent parsing a JSON file it just wrote. In a
real session that was 13 of 27 commands asked about, all of them local work.

Codex and Hermes both put a model in front of that judgement. Codex calls it a
guardian subagent (`approvals_reviewer = "auto_review"`); Hermes credits it
directly -- `_smart_approve`'s docstring says "Inspired by OpenAI Codex's Smart
Approvals guardian subagent" -- and returns three states, not two.

**Three states is the point.** A binary approve/deny forces the model to be
confident about something a regex could not decide. `escalate` says "I do not
know", and the human is asked. That is what keeps a model from rubber-stamping a
genuinely dangerous command just because the prompt asked it to decide.

The reviewer never *blocks* on its own initiative: `deny` still goes to the
human, because a model reading a shell string is not a security boundary. What it
can do is clear the command, which is the common case and the one that costs the
user a prompt.

Anything unexpected -- no provider, a timeout, unparseable output -- is an
`escalate`. Failing open on a safety judgement is the wrong direction.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

log = logging.getLogger(__name__)

Verdict = Literal["approve", "deny", "escalate"]

#: Reviews one command; returns what to do about it.
Reviewer = Callable[[str, str], Awaitable[str]]

#: Words a model reaches for, mapped onto the three verdicts in `parse_verdict`.
#: Asked for one word, it often answers with a neighbour.
_VERDICT_WORDS = "approve|allow|ok|safe|deny|block|reject|unsafe|escalate"
_JSON_VERDICT = re.compile(
    rf'"(?:verdict|decision)"\s*:\s*"({_VERDICT_WORDS})"', re.IGNORECASE
)
_BARE_VERDICT = re.compile(
    rf"^\s*({_VERDICT_WORDS})\b", re.IGNORECASE | re.MULTILINE
)

SYSTEM = """\
You review shell commands an AI coding agent wants to run. A rule matched and \
the user is about to be interrupted to approve or reject it.

Answer with one word plus at most one sentence of reasoning:

- approve: the command is safe. It only reads or writes files, runs a local \
script the agent itself wrote, or queries a service. Nothing outside the \
workspace is destroyed and nothing remote is executed.
- deny: the command would destroy data, exfiltrate credentials, or execute code \
fetched from the network.
- escalate: you are not sure. This is a normal answer, not a failure.

When a rule fired on shape alone and the command is plainly benign, say approve. \
When the command really is dangerous, say deny. When you cannot tell, say \
escalate."""

PROMPT = """The command was flagged as: {reason}

Command:
```
{command}
```

Verdict:"""


@dataclass(frozen=True)
class Review:
    verdict: Verdict
    reason: str = ""

    @property
    def clears(self) -> bool:
        """Whether the reviewer was confident enough to answer without a human."""
        return self.verdict == "approve"


def parse_verdict(raw: str | None) -> Verdict:
    """Read a verdict out of a model response.

    Tolerates a bare word and a JSON object, because a model asked for one word
    will sometimes hand back either. Anything unrecognised escalates.
    """
    if not raw:
        return "escalate"
    match = _JSON_VERDICT.search(raw)
    if match is None:
        match = _BARE_VERDICT.search(raw)
    if match is None:
        return "escalate"
    word = match.group(1).lower()
    if word in ("approve", "allow", "ok", "safe"):
        return "approve"
    if word in ("deny", "block", "reject", "unsafe"):
        return "deny"
    return "escalate"


def build_reviewer(
    llm: object | None,
    model: str,
    *,
    timeout: float = 20.0,
) -> Reviewer:
    """A reviewer backed by *llm*, or one that always escalates.

    Args:
        llm: Anything with `stream_text_once`-compatible behaviour, or None.
        model: Model to ask.
        timeout: Seconds before giving up and escalating.

    Returns:
        A reviewer coroutine. With no provider it is a constant `escalate`, so
        callers need no branch of their own for the unconfigured case.
    """

    async def review(command: str, reason: str) -> str:
        if llm is None:
            return "escalate"
        try:
            from nova.llm.oneshot import stream_text_once

            text = await stream_text_once(
                llm,  # type: ignore[arg-type]
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": PROMPT.format(reason=reason, command=command)},
                ],
                model=model,
                timeout=timeout,
                label="shell approval review",
            )
        except Exception as exc:  # a review failure is not a verdict
            log.info("shell review unavailable (%s); escalating", exc)
            return "escalate"
        verdict = parse_verdict(text)
        log.debug("shell review of %r: %s", command[:60], verdict)
        return verdict

    return review


def parse_review_json(payload: str) -> dict | None:
    """Best-effort read of a JSON object from a model response."""
    start = payload.find("{")
    if start < 0:
        return None
    try:
        value = json.loads(payload[start : payload.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None
