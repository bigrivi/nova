"""Append-only usage log for the web_search backend ring.

Neither public backend publishes the size of its keyless daily allowance, so
the only honest way to learn the real ceiling is to record what happens during
ordinary use and let the observed rate limits reveal it. Every call appends one
JSON object, which keeps the file greppable and cheap to write, and keeps the
measurement passive: no probing traffic, no extra load on a shared service.

Two outcomes matter for quota work. ``rate_limited`` marks the first 429 of a
window, which is what bounds the ceiling. ``empty`` marks a backend that
answered but matched nothing, which distinguishes an exhausted quota from a
backend that simply had nothing to say.

Backends that report their own remaining allowance add it to the record, so
``quota_low`` in :func:`render` shows whether a free pool is reserved for this
client or drained by every other caller on the internet.
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from nova.settings import get_settings

LOGGER = logging.getLogger(__name__)

USAGE_FILENAME = "web_search_usage.jsonl"
OUTCOME_OK = "ok"
OUTCOME_EMPTY = "empty"
OUTCOME_RATE_LIMITED = "rate_limited"
SECONDS_PER_DAY = 86400


def usage_path() -> Path:
    """Return the usage log path inside the configured logs directory."""
    return get_settings().logs_dir / USAGE_FILENAME


def record_usage(
    backend: str, outcome: str, quota_remaining: int | None = None
) -> None:
    """Append one usage record.

    Never raises: usage accounting must not be able to break a search.

    Args:
        backend: Backend name, e.g. ``exa``.
        outcome: Outcome label, e.g. ``ok`` or ``rate_limited``.
        quota_remaining: Calls left in the current window, when the backend
            reports it. Tracking the low-water mark distinguishes a free pool
            reserved for this client from one shared with every other caller.
    """
    try:
        path = usage_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "ts": time.time(),
            "backend": backend,
            "outcome": outcome,
        }
        if quota_remaining is not None:
            record["remaining"] = quota_remaining
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        LOGGER.debug("could not record web_search usage: %s", exc)


def summarize(days: int = 7) -> list[dict[str, Any]]:
    """Aggregate recorded usage per day and backend.

    Args:
        days: How many days of history to include.

    Returns:
        One row per (date, backend), newest date first, each carrying counts
        for ``ok``, ``empty``, ``rate_limited``, and ``other_errors``.
    """
    path = usage_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []

    cutoff = time.time() - max(days, 1) * SECONDS_PER_DAY
    buckets: dict[str, dict[str, dict[str, Any]]] = defaultdict(
        lambda: defaultdict(lambda: {"outcomes": Counter(), "remaining": []})
    )
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            stamp = float(record["ts"])
            backend = str(record["backend"])
            outcome = str(record["outcome"])
        except (ValueError, TypeError, KeyError):
            continue
        if stamp < cutoff:
            continue
        day = time.strftime("%Y-%m-%d", time.localtime(stamp))
        bucket = buckets[day][backend]
        bucket["outcomes"][outcome] += 1
        remaining = record.get("remaining")
        if isinstance(remaining, int):
            bucket["remaining"].append(remaining)

    known = {OUTCOME_OK, OUTCOME_EMPTY, OUTCOME_RATE_LIMITED}
    rows: list[dict[str, Any]] = []
    for day in sorted(buckets, reverse=True):
        for backend in sorted(buckets[day]):
            bucket = buckets[day][backend]
            outcomes: Counter[str] = bucket["outcomes"]
            low = bucket["remaining"]
            other = sum(v for k, v in outcomes.items() if k not in known)
            rows.append(
                {
                    "date": day,
                    "backend": backend,
                    "ok": outcomes.get(OUTCOME_OK, 0),
                    "empty": outcomes.get(OUTCOME_EMPTY, 0),
                    "rate_limited": outcomes.get(OUTCOME_RATE_LIMITED, 0),
                    "other_errors": other,
                    "total": sum(outcomes.values()),
                    "quota_low": min(low) if low else None,
                    "quota_seen": len(low),
                }
            )
    return rows


def render(rows: list[dict[str, Any]]) -> str:
    """Render summary rows as a fixed-width table.

    Args:
        rows: Rows produced by :func:`summarize`.

    Returns:
        A table string, or a hint when nothing has been recorded yet.
    """
    if not rows:
        return (
            "No web_search usage recorded yet. The log is written on the first search."
        )

    header = (
        f"{'date':<12} {'backend':<10} {'ok':>5} {'empty':>6} "
        f"{'429':>5} {'errors':>7} {'total':>6} {'quota_low':>10}"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        low = row["quota_low"]
        lines.append(
            f"{row['date']:<12} {row['backend']:<10} {row['ok']:>5} "
            f"{row['empty']:>6} {row['rate_limited']:>5} "
            f"{row['other_errors']:>7} {row['total']:>6} "
            f"{str(low) if low is not None else '-':>10}"
        )
    lines.append("")
    lines.append("quota_low is the lowest remaining-calls figure the backend reported.")
    lines.append(
        "It falling by much more than this agent's own call count means the free"
    )
    lines.append("pool is shared with other callers.")
    lines.append(f"log: {usage_path()}")
    return "\n".join(lines)
