"""Nova catalogue adapter around portable pricing math."""

from __future__ import annotations

from typing import Any

from novakit.pricing import CACHE_READ, INPUT, OUTPUT, cheapest_prices, numeric_prices
from novakit.pricing import estimate_cost_from_prices as _estimate_cost_from_prices
from novakit.pricing import usage_cost as _usage_cost

from nova.registry.catalogue import COST_KEY, load
from nova.settings import Settings


def _numbers(raw: object) -> dict[str, float]:
    return numeric_prices(raw)


def _price_sum(prices: dict[str, float]) -> float:
    return prices.get(INPUT, 0.0) + prices.get(OUTPUT, 0.0)


def model_prices(settings: Settings, model: str | None) -> dict[str, float] | None:
    """Return the cheapest catalogue price for *model*, or None when unknown.

    Args:
        settings: Loaded settings used to resolve the catalogue snapshot.
        model: Model identifier recorded on a message.

    Returns:
        Dollars per million tokens, or None when the catalogue has no price.
    """
    if not model:
        return None
    return cheapest_prices(
        (models.get(model) or {}).get(COST_KEY) for models in load(settings).values()
    )


def estimate_cost(
    settings: Settings,
    model: str | None,
    tokens_input: int | None,
    tokens_output: int | None,
    cache_read_tokens: int | None = None,
) -> float | None:
    """Estimate one call's dollar cost from Nova's catalogue.

    Args:
        settings: Loaded settings used to resolve the catalogue snapshot.
        model: Model that answered.
        tokens_input: Provider-reported prompt tokens.
        tokens_output: Provider-reported completion tokens.
        cache_read_tokens: Prompt tokens served from cache.

    Returns:
        Estimated dollars, or None when the model has no known price.
    """
    return _estimate_cost_from_prices(
        model_prices(settings, model),
        tokens_input,
        tokens_output,
        cache_read_tokens,
    )


def usage_cost(settings: Settings, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Annotate aggregated usage rows using Nova's catalogue.

    Args:
        settings: Loaded settings used to resolve the catalogue snapshot.
        rows: Aggregated model usage rows.

    Returns:
        Total priced cost and unpriced-model counts.
    """
    return _usage_cost(rows, lambda model: model_prices(settings, model))


__all__ = [
    "CACHE_READ",
    "INPUT",
    "OUTPUT",
    "estimate_cost",
    "model_prices",
    "usage_cost",
]
