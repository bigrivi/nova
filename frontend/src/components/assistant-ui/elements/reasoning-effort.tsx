/* eslint-disable react-refresh/only-export-components */
"use client";

import type { ComponentProps, KeyboardEvent, RefObject } from "react";
import { cn } from "@/lib/utils";
import { field } from "./surfaces";
import { announced, pct } from "../utils/range";

export interface EffortLevel {
  key: string;
  label: string;
  /**
   * Token budget for this rung, when the app knows one. It is optional because
   * what a level costs is the provider's business: a gateway's ladder carries no
   * numbers, and a made-up budget would put a false figure on screen and in the
   * accessibility tree. Without it the bar and its readout are not rendered.
   */
  budget?: number;
}

export type ReasoningEffortProps = Omit<
  ComponentProps<"div">,
  "children" | "levels" | "selectedKey" | "onSelect"
> & {
  levels: readonly EffortLevel[];
  selectedKey: string;
  onSelect?: (key: string) => void;
  /** Tokens spent on reasoning, paired with the level's own `budget`. */
  spent?: number;
  /** Heading for the control. Upstream hardcodes the English "Thinking". */
  label?: string;
  /** The level buttons, so arrow keys can move between them. */
  buttonsRef?: RefObject<(HTMLButtonElement | null)[] | null>;
};

const fmt = (n: number) => n.toLocaleString("en-US");

export function ReasoningEffort({
  levels,
  selectedKey,
  onSelect,
  spent,
  label = "Thinking",
  buttonsRef,
  onKeyDown,
  className,
  ...props
}: ReasoningEffortProps) {
  const budget = levels.find((level) => level.key === selectedKey)?.budget ?? 0;
  // A budget of zero means "unknown", not "spent nothing", so the bar stays
  // hidden rather than showing an empty track that reads as a real reading.
  const measurable = budget > 0 && typeof spent === "number";
  const used = measurable ? pct(spent as number, budget) : 0;

  return (
    <div
      data-slot="reasoning-effort"
      className={cn("flex w-full max-w-sm flex-col gap-2.5", className)}
      onKeyDown={onKeyDown}
      {...props}
    >
      <div className="flex items-baseline justify-between">
        <span className="text-[13.5px] font-medium">{label}</span>
        {measurable && (
          <span className="text-foreground/35 tabular-nums text-xs">
            {fmt(spent as number)} / {fmt(budget)}
          </span>
        )}
      </div>

      <div className={cn(field, "flex gap-0.5 rounded-full p-0.5")}>
        {levels.map((level, index) => {
          const active = level.key === selectedKey;
          const className = cn(
            "flex-1 rounded-full py-1 text-xs font-medium transition-[background-color,color,scale] duration-150",
            onSelect && "active:scale-[0.97]",
            active
              ? "bg-background text-foreground/90"
              : onSelect
                ? "text-foreground/45 hover:text-foreground/70"
                : "text-foreground/45",
          );
          return onSelect ? (
            <button
              key={level.key}
              type="button"
              aria-pressed={active}
              // Only the selected rung is in the tab order; the arrow keys move
              // between them, which is what a radiogroup does natively.
              tabIndex={active ? 0 : -1}
              ref={(node) => {
                if (!buttonsRef) return;
                buttonsRef.current = buttonsRef.current ?? [];
                buttonsRef.current[index] = node;
              }}
              onClick={() => onSelect(level.key)}
              data-key={level.key}
              className={className}
            >
              {level.label}
            </button>
          ) : (
            <span
              key={level.key}
              aria-current={active ? "true" : undefined}
              className={className}
            >
              {level.label}
            </span>
          );
        })}
      </div>

      {measurable && (
        <span
          role="progressbar"
          aria-label={`${label} budget used`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={announced(used)}
          aria-valuetext={`${fmt(spent as number)} of ${fmt(budget)}`}
          className="bg-foreground/[0.06] h-[3px] w-full overflow-hidden rounded-full"
        >
          <span
            className="block h-full rounded-full bg-blue-500 transition-[width] duration-500 motion-reduce:transition-none dark:bg-blue-400"
            style={{ width: `${used}%` }}
          />
        </span>
      )}
    </div>
  );
}

/**
 * Which rung the arrow keys land on, or null when the key is not ours.
 *
 * Separate from the DOM work so the wrap-around and the out-of-range cases can
 * be checked without a browser: a radiogroup this small is easy to get wrong
 * at the two ends, where the errors are invisible until someone presses the
 * key twice.
 */
export function nextEffortIndex(
  key: string,
  current: number,
  count: number,
): number | null {
  if (count <= 0) return null;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  const step = key === "ArrowRight" ? 1 : key === "ArrowLeft" ? -1 : 0;
  if (step === 0) return null;
  // Focus outside the group (current === -1) enters at the first rung rather
  // than wrapping in from an arbitrary end.
  if (current < 0) return 0;
  return (current + step + count) % count;
}

/** Move focus and selection along the level buttons with the arrow keys. */
export function handleEffortArrowKeys(
  event: KeyboardEvent<HTMLDivElement>,
  buttons: RefObject<(HTMLButtonElement | null)[] | null>,
  select: (key: string) => void,
) {
  const items = (buttons.current ?? []).filter(
    (node): node is HTMLButtonElement => node !== null,
  );
  const current = items.findIndex((node) => node === document.activeElement);
  const next = nextEffortIndex(event.key, current, items.length);
  if (next === null) return;

  event.preventDefault();
  event.stopPropagation();
  items[next]?.focus();
  const key = items[next]?.dataset.key;
  if (key) select(key);
}
