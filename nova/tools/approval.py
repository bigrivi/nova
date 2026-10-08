from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class ApprovalRequest:
    id: str
    command: str
    description: str
    approved: bool | None = None
    session_id: str = ""
    # Which rule asked. This is what a grant is recorded against, so it must be
    # the rule's identity and not the command text -- see ApprovalManager.
    rule: str = ""
    # Which command family within that rule, e.g. "git push *". Empty when the
    # line could not be read into families, which is also what makes the grant
    # cover the whole rule.
    family: str = ""
    # Which inline script within that family. Empty when the line carries no
    # readable `-c` literal, which is also what makes the grant cover the whole
    # family.
    digest: str = ""

    # There were ``created_at``/``expires_at`` fields and a ``default_timeout=60``
    # here. Nothing ever read them: ``wait_with_heartbeat`` waits on an
    # ``asyncio.Event`` and has no deadline, so ``timeout=0`` only *appeared* to mean
    # "wait forever" because ``0 or 60`` picked the default and the default was
    # never applied. The code implied a timeout that did not exist, and
    # ``timeout=0`` read as deliberate while being an accident of `or``.
    #
    # Removing it is also the correct behaviour, not a retreat: an approval the
    # user did not answer should wait, not expire. A timeout here would silently
    # deny commands the user was still reading.


class ApprovalManager:
    """Tracks pending approvals and the grants made from them.

    A grant names a *rule*, a *command family* and an *inline script*, never a
    command. The earliest version stored the command text, which made "always
    allow" inert for exactly the commands that most need it: an agent that
    interpolates a URL, a timestamp or a temp path never repeats itself, so the
    stored string was never seen again.

    The rule alone is too wide in the other direction. One rule can cover commands
    that are not interchangeable -- `git force push` and `git clean -fd` are both
    "destructive git" but a user allowing one has not agreed to the other -- so
    the family narrows it to the command the user actually saw. The prefix table
    behind the family comes from OpenCode's, which encodes the same convention:
    `git push` and `git checkout` are different commands however alike their
    rules are.

    The family is still not exact for a piped interpreter, because a family names
    a program and not what the program is told to do. `curl … | python3 -c
    "exec(sys.stdin.read())"` and a base64 loader are both `curl * python3 *` under
    the same rule, so a grant for the first used to authorise the second -- the
    user approving something they never saw. The digest narrows the key to the
    script that was read, and it is the third part because the script is the only
    part that comes from the command text rather than from a table of conventions.

    Each level is optional and each level absent is wider, never narrower: no rule
    means nothing to match, no family means the whole rule, no digest means the
    whole family. A request that cannot fill one of them therefore still works
    rather than becoming unrememberable, and a grant recorded without a digest
    keeps exactly the width it always had.

    Grants live in memory for the life of the process, so widening the key only
    costs approvals made earlier in the same run. There is nothing to migrate.
    """

    def __init__(self) -> None:
        self._pending: dict[str, ApprovalRequest] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._grants: dict[str, set[tuple[str, str, str]]] = {}

    def pre_request(
        self,
        command: str,
        description: str = "",
        session_id: str = "",
        rule: str = "",
        family: str = "",
        digest: str = "",
    ) -> str:
        """Create a pending approval request and return its id (non-blocking).

        Returns "" when the session already holds a grant covering this *rule*,
        *family* and *digest*. With no rule supplied there is nothing to match on,
        so the command is always asked -- that path is the tool asserting a danger
        without naming the rule, and guessing which rule it meant would silently
        widen the grant.

        A grant stored with no family covers every command under its rule. That is
        deliberate, and it is the wide direction: it only happens when the command
        line could not be read into a family, where a grant too wide costs one
        prompt and a family that does not match costs a grant that silently never
        applies.

        A grant stored with a digest does **not** answer for a command whose own
        digest is absent. That is the opposite of the family rule above, and it is
        deliberate. The family is unreadable only for a line the grammar could not
        parse, which is rare, whereas an absent digest is the ordinary case for
        every command carrying no inline script. Letting a script-specific approval
        cover one of those would run `python3 -m http.server` on the strength of
        someone having read an unrelated `-c` script.

        The request never expires. Waiting is the point: an unanswered prompt
        should hold the turn open, not quietly deny the command.
        """
        if rule and self._granted(rule, family, digest, session_id):
            return ""

        req_id = uuid.uuid4().hex[:12]
        self._pending[req_id] = ApprovalRequest(
            id=req_id,
            command=command,
            description=description,
            session_id=session_id,
            rule=rule,
            family=family,
            digest=digest,
        )
        self._events[req_id] = asyncio.Event()
        return req_id

    def _granted(self, rule: str, family: str, digest: str, session_id: str) -> bool:
        """Whether the session holds a grant covering this rule, family and script.

        The two narrowing parts match on equality or absence *on the granted side
        only*, so a grant made without them keeps the width it had. Requiring a
        digest to be present on both sides would invalidate every existing grant on
        its first use, which is the opposite failure: a user who approved something
        would be asked again for the identical command.
        """
        for granted_rule, granted_family, granted_digest in self._grants.get(
            session_id, ()
        ):
            if granted_rule != rule:
                continue
            if granted_family and family and granted_family != family:
                continue
            # Asymmetric on purpose, and the asymmetry is the whole reason this
            # level exists. `granted_digest and granted_digest != digest` rather
            # than the family shape above: a grant that names a script covers that
            # script and nothing else, including nothing at all.
            #
            # The family clause tolerates a missing family on either side because
            # a missing *family* means the grammar could not read the line, which
            # is rare. A missing *digest* is the ordinary shape of every command
            # with no inline script, so tolerating it would let one approved `-c`
            # script authorise `python3 -m http.server`.
            #
            # The reverse stays wide: a grant recorded without a digest -- one made
            # before this level existed, or for a command with no script -- still
            # covers the family, which is what it always did.
            if granted_digest and granted_digest != digest:
                continue
            return True
        return False

    async def wait_with_heartbeat(
        self,
        req_id: str,
        heartbeat_interval: int = 15,
    ) -> AsyncGenerator[bool | None, None]:
        """Async generator: yields None for each heartbeat tick,
        then yields True if approved, False if rejected."""
        if not req_id:
            yield True
            return
        event = self._events.get(req_id)
        if event is None:
            yield False
            return
        try:
            while True:
                try:
                    await asyncio.wait_for(event.wait(), timeout=heartbeat_interval)
                except TimeoutError:
                    yield None
                    continue
                req = self._pending.get(req_id)
                if req is None or req.approved is None:
                    continue
                # Drop it before yielding, not only in `finally`. A consumer that
                # `break`s out of the loop leaves the generator suspended, so the
                # `finally` waits on garbage collection -- and "a second resolve
                # returns False" is what makes a replayed approve a 404 at the
                # endpoint. Relying on refcounts for that is not a guarantee.
                self._discard(req_id)
                yield req.approved
                return
        finally:
            # Covers the abandoned case: the consumer walked away without a verdict.
            self._discard(req_id)

    def _discard(self, req_id: str) -> None:
        self._pending.pop(req_id, None)
        self._events.pop(req_id, None)

    def get_session_id_for_request(self, request_id: str) -> str | None:
        """Return the owning session_id for a pending approval request.

        Returns None when the request_id is unknown or already consumed.
        Used by POST /api/chat/approve to enforce session binding:
        a request_id may only be resolved from its owning session_id,
        otherwise the endpoint answers 404.
        """
        approval_request = self._pending.get(request_id)
        if approval_request is None:
            return None
        return approval_request.session_id

    def resolve(self, req_id: str, approved: bool, remember: bool = False) -> bool:
        req = self._pending.get(req_id)
        if req is None:
            return False
        req.approved = approved
        if approved and remember and req.rule and req.session_id:
            self._grant(req.rule, req.family, req.digest, req.session_id)
        event = self._events.get(req_id)
        if event:
            event.set()
        return True

    def _grant(self, rule: str, family: str, digest: str, session_id: str) -> None:
        self._grants.setdefault(session_id, set()).add((rule, family, digest))

    def add_to_allowlist(
        self, rule: str, session_id: str = "", family: str = "", digest: str = ""
    ) -> None:
        """Grant *rule* (optionally narrowed to *family* and *script*) directly.

        A grant with no session is dropped rather than filed under the empty
        string. ``ToolInvoker`` falls back to ``""`` when it cannot resolve a
        session, so storing it there would make every id-less context share one
        set of grants -- and an approval the user gave in one turn would silently
        authorise the same rule in another. Losing the grant only costs a repeat
        prompt; the alternative widens an authorisation the user never scoped.
        """
        if rule and session_id:
            self._grant(rule, family, digest, session_id)

    def allowlist_for(self, session_id: str) -> set[tuple[str, str, str]]:
        """The (rule, family, digest) triples granted to *session_id*."""
        return set(self._grants.get(session_id, ()))

    def get_pending(self) -> list[ApprovalRequest]:
        return [r for r in self._pending.values() if r.approved is None]


_manager: ApprovalManager | None = None


def get_approval_manager() -> ApprovalManager:
    global _manager
    if _manager is None:
        _manager = ApprovalManager()
    return _manager
