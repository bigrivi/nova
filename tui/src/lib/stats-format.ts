/** Number formatting for the usage panel: compact tokens, readable money. */

const UNITS = [
    { size: 1_000_000_000, suffix: "B" },
    { size: 1_000_000, suffix: "M" },
    { size: 1_000, suffix: "K" },
] as const;

/**
 * A token count in the shortest form that keeps a decimal.
 *
 * Args:
 *   value: A non-negative count.
 *
 * Returns:
 *   ``"512"``, ``"3.2K"``, ``"42.1M"``, ``"1.2B"``. The decimal is dropped
 *   when it is zero, so a round number reads as a round number.
 */
export function compactTokens(value: number): string {
    const count = Math.max(0, Math.round(value));
    for (const unit of UNITS) {
        if (count < unit.size) continue;
        const scaled = count / unit.size;
        const text = scaled >= 100 ? scaled.toFixed(0) : scaled.toFixed(1);
        return `${text.replace(/\.0$/, "")}${unit.suffix}`;
    }
    return String(count);
}

/**
 * A dollar amount, or a dash when the price is unknown.
 *
 * Args:
 *   cost: The estimate, or undefined when no price was known.
 *
 * Returns:
 *   ``"$4.82"``, ``"$0.00"`` (a real answer: known to be free), ``"<$0.01"``
 *   for a nonzero amount below a cent, or ``"—"`` when unknown.
 */
export function formatCost(cost: number | undefined): string {
    if (cost === undefined) return "—";
    if (cost === 0) return "$0.00";
    if (cost < 0.01) return "<$0.01";
    if (cost >= 1000) return `$${(cost / 1000).toFixed(1)}K`;
    return `$${cost.toFixed(2)}`;
}

/** ``"4h 12m"``, ``"12m"``, ``"48s"`` -- a duration a reader can skim. */
export function formatDuration(milliseconds: number): string {
    const seconds = Math.max(0, Math.round(milliseconds / 1000));
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ${minutes % 60}m`;
    return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}
