"""What a model costs, from the catalogue Nova already downloads.

Prices are dollars per million tokens, as models.dev states them per model.
The same model can be served at different prices by different providers, and a
message records the model but not the provider, so the cheapest stated price is
used: it is a lower bound, which is the honest direction for an estimate.

A model the catalogue does not know has no price. Callers report that as
"unknown" rather than zero -- "we do not know" and "it was free" are different
answers, and only one of them is safe to put in a spending report.
"""

from __future__ import annotations

from typing import Any

from nova.registry.catalogue import COST_KEY, load
from nova.settings import Settings

#: The price of one million input tokens.
INPUT = "input"

#: The price of one million output tokens.
OUTPUT = "output"

#: The price of one million tokens served from the provider's cache.
CACHE_READ = "cache_read"

#: One million tokens, the unit models.dev quotes prices in.
_PER_MILLION = 1_000_000


def _numbers(raw: object) -> dict[str, float]:
    """The numeric prices in one catalogue cost block."""
    if not isinstance(raw, dict):
        return {}
    prices: dict[str, float] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        prices[str(key)] = float(value)
    return prices


def _price_sum(prices: dict[str, float]) -> float:
    return prices.get(INPUT, 0.0) + prices.get(OUTPUT, 0.0)


def model_prices(settings: Settings, model: str | None) -> dict[str, float] | None:
    """The cheapest known price for *model*, or None when nothing is stated.

    Args:
        settings: Loaded settings, for the catalogue snapshot.
        model: The model id a message recorded.

    Returns:
        ``{input, output, cache_read}`` in dollars per million tokens, or None.
    """
    if not model:
        return None
    best: dict[str, float] | None = None
    for models in load(settings).values():
        prices = _numbers((models.get(model) or {}).get(COST_KEY))
        if not prices:
            continue
        if best is None or _price_sum(prices) < _price_sum(best):
            best = prices
    return best


def estimate_cost(
    settings: Settings,
    model: str | None,
    tokens_input: int | None,
    tokens_output: int | None,
    cache_read_tokens: int | None = None,
) -> float | None:
    """The dollar cost of one call, or None when its price is unknown.

    Args:
        settings: Loaded settings, for the catalogue snapshot.
        model: The model that answered.
        tokens_input: Prompt tokens the provider reported.
        tokens_output: Completion tokens the provider reported.
        cache_read_tokens: Prompt tokens served from the provider's cache.

    Returns:
        The estimated cost in dollars, or None when ``model`` has no known
        price.
    """
    prices = model_prices(settings, model)
    if prices is None:
        return None
    return (
        (tokens_input or 0) / _PER_MILLION * prices.get(INPUT, 0.0)
        + (tokens_output or 0) / _PER_MILLION * prices.get(OUTPUT, 0.0)
        + (cache_read_tokens or 0) / _PER_MILLION * prices.get(CACHE_READ, 0.0)
    )


def usage_cost(settings: Settings, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Total and per-model cost for aggregated usage rows.

    Args:
        settings: Loaded settings, for the catalogue snapshot.
        rows: ``{"model", "input", "output", "cache_read"}`` per model.

    Returns:
        ``{"total", "priced", "unpriced_models"}``: the priced total, whether
        every model had a price, and how many did not.
    """
    total = 0.0
    unpriced = 0
    for row in rows:
        cost = estimate_cost(
            settings,
            str(row.get("model") or ""),
            int(row.get("input") or 0),
            int(row.get("output") or 0),
            int(row.get("cache_read") or 0),
        )
        if cost is None:
            unpriced += 1
            continue
        row["cost"] = cost
        total += cost
    return {"total": total, "priced": unpriced == 0, "unpriced_models": unpriced}
