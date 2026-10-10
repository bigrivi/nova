"""Probe: verify suspected false-positive / silent-allow shapes against Nova's classifier."""

from __future__ import annotations

import asyncio

from nova.tools.shell import classify, decide

# (command, workspace for scope check)
CASES: list[tuple[str, str | None]] = [
    # --- suspected whole-line substring false positives ---
    ('git commit -m "docs: explain why git push --force is dangerous"', None),
    ('grep -rn "killall -9" scripts/', None),
    ('echo "DELETE FROM users" > migrations/0001.sql', None),
    ("cat > docs/safety.md << EOF\nthen rm -rf /\nEOF", None),
    ('git log --format="%s" | grep "DROP TABLE"', None),
    # --- common benign agent idioms that still ask ---
    ('bash -lc "python -m pytest -q"', None),
    ("python3 << 'EOF'\nprint(1)\nEOF", None),
    ("docker compose down", None),
    ("curl -s https://api.example/x | grep -w node", None),
    # --- suspected silent allows ---
    ("npm test && git reset --hard", None),
    ("rm -rf ../outside-of-workspace", "/Users/andy/Workspace/codes/ai/nova"),
    ("cp ~/.ssh/id_rsa /tmp/key-backup", None),
    ("ln -s /etc/passwd ./link", "/Users/andy/Workspace/codes/ai/nova"),
    ("cp payload /etc", None),
    ("mv payload /usr/local/bin", None),
    # --- allow-prefix interaction ---
    ("git push origin main && chmod 777 /tmp/x", None),
]


async def main() -> None:
    for command, workspace in CASES:
        decision = classify(command, workspace)
        verdict = await decide(command, workspace)
        first = command.splitlines()[0]
        print(f"{decision.effect:5} | {first[:78]}")
        print(
            f"      rule={decision.rule!r} family={verdict.family!r} digest={verdict.digest!r}"
        )


if __name__ == "__main__":
    asyncio.run(main())
