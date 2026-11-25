#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACTS="$(mktemp -d "${TMPDIR:-/tmp}/novakit-wheel-smoke.XXXXXX")"

cd "$ROOT"
uv build --package novakit --wheel --out-dir "$ARTIFACTS/wheel"
WHEEL="$(find "$ARTIFACTS/wheel" -name '*.whl' -print -quit)"
if [[ -z "$WHEEL" ]]; then
    printf 'No novakit wheel was produced.\n' >&2
    exit 1
fi
uv pip install --target "$ARTIFACTS/install" --no-deps "$WHEEL"

PYTHONPATH="$ARTIFACTS/install" "$ROOT/.venv/bin/python" - <<'PY'
import asyncio
import sys
from pathlib import Path

import novakit
from novakit import Agent, AgentConfig
from novakit.events import AgentEvent
from novakit.llm import FakerLLMProvider

assert "nova" not in sys.modules
assert (Path(novakit.__file__).parent / "py.typed").exists()


async def main() -> None:
    agent = Agent(AgentConfig(model="fake"), FakerLLMProvider(seed=1))
    frames = [frame async for frame in agent.chat_stream("hello")]
    assert frames[-1][0] is AgentEvent.DONE
    assert len(await agent.session.get_messages()) == 2


asyncio.run(main())
print("novakit wheel smoke test passed")
PY

printf 'Artifacts retained at: %s\n' "$ARTIFACTS"
