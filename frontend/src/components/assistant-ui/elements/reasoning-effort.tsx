/* eslint-disable react-refresh/only-export-components */
"use client";

import { cn } from "@/lib/utils";
import { useCallback, useRef, type ComponentProps, type ReactNode } from "react";
import { field } from "./surfaces";

export interface EffortLevel {
  key: string;
  label: string;
  /**
   * Token budget for this rung, when the app knows one. It is optional because
   * what a level costs is the provider's business: a gateway's ladder carries no
   * numbers, and a made-up budget would put a false figure on screen and in the
   * accessibility tree. Without it the budget readout is not rendered.
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
  /** Replaces the level captions when the raw ids would not read well. */
  renderLevel?: (level: EffortLevel) => ReactNode;
};

const fmt = (n: number) => n.toLocaleString("en-US");

/**
 * Track width by how many rungs there are, so a three-level ladder does not
 * spread across the same space a six-level one needs.
 */
export function trackWidth(count: number): number {
  if (count >= 6) return 280;
  if (count === 5) return 250;
  if (count === 4) return 220;
  if (count === 3) return 190;
  return 160;
}

/**
 * Half a rung dot, in pixels. The rungs are inset by this at each end so they
 * sit inside the rail rather than on its tips, while the rail itself still runs
 * the full width.
 */
const DOT_INSET = 2;

/**
 * Where a level sits along the track, as a 0…1 ratio of the usable span.
 *
 * With the per-rung captions gone the rungs no longer have to line up with a
 * column of text, so they span the full width and the rail needs no inset of
 * its own.
 */
export function effortRatio(index: number, count: number): number {
  if (count <= 1) return 0;
  return index / (count - 1);
}

/** The rung a pointer at *ratio* (0…1 across the track) belongs to. */
export function effortRungAt(ratio: number, count: number): number {
  if (count <= 1) return 0;
  if (Number.isNaN(ratio)) return 0;
  return Math.min(count - 1, Math.max(0, Math.round(ratio * (count - 1))));
}

/** A CSS `left`/`width` that keeps a dot-sized gap at both ends of the rail. */
function dotOffset(ratio: number): string {
  return `calc(${DOT_INSET}px + (100% - ${DOT_INSET * 2}px) * ${ratio})`;
}

export function ReasoningEffort({
  levels,
  selectedKey,
  onSelect,
  spent,
  label = "Thinking",
  renderLevel,
  className,
  ...props
}: ReasoningEffortProps) {
  const count = levels.length;
  const index = Math.max(
    0,
    levels.findIndex((level) => level.key === selectedKey),
  );
  const track = useRef<HTMLDivElement>(null);
  const budget = levels[index]?.budget ?? 0;
  const measurable = budget > 0 && typeof spent === "number";

  /** Nearest rung to a pointer position, so a drag lands where it was dropped. */
  const rungAt = useCallback(
    (clientX: number): number => {
      const rect = track.current?.getBoundingClientRect();
      if (!rect || rect.width === 0) return 0;
      return effortRungAt((clientX - rect.left) / rect.width, count);
    },
    [count],
  );

  const choose = useCallback(
    (next: number) => {
      const level = levels[next];
      if (level && level.key !== selectedKey) onSelect?.(level.key);
    },
    [levels, onSelect, selectedKey],
  );

  // Dragging and releasing past the end should still land on a rung, so the
  // pointer is captured for the whole gesture rather than only while over the
  // track.
  const dragging = useRef(false);
  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!onSelect || count <= 1) return;
    dragging.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    choose(rungAt(event.clientX));
  };
  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return;
    choose(rungAt(event.clientX));
  };
  const onPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!onSelect || count <= 1) return;
    const step = event.key === "ArrowRight" || event.key === "ArrowUp" ? 1
      : event.key === "ArrowLeft" || event.key === "ArrowDown" ? -1
      : 0;
    if (step === 0 && event.key !== "Home" && event.key !== "End") return;
    // The picker is a cmdk list, which also answers these keys; stop here so
    // one keypress moves the level and not the model highlight.
    event.preventDefault();
    event.stopPropagation();
    const next =
      event.key === "Home" ? 0
      : event.key === "End" ? count - 1
      : Math.min(count - 1, Math.max(0, index + step));
    choose(next);
  };

  return (
    <div
      data-slot="reasoning-effort"
      className={cn("flex w-full flex-col gap-2", className)}
      style={{ minWidth: trackWidth(count) }}
      {...props}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-muted-foreground shrink-0 text-xs whitespace-nowrap">
          {label}
        </span>
        {/* Only the active level is named. A caption per rung would need a
            column each to stay legible, and the rungs are already ordered
            left to right, so the extra row mostly repeated the track. */}
        <span className="text-foreground min-w-0 truncate text-xs font-medium">
          {levels[index]?.label}
        </span>
        {measurable && (
          <span className="text-muted-foreground/70 shrink-0 text-[11px] tabular-nums">
            {fmt(spent as number)} / {fmt(budget)}
          </span>
        )}
      </div>

      {count > 1 ? (
        <>
          <div
            ref={track}
            role="slider"
            tabIndex={onSelect ? 0 : -1}
            aria-label={label}
            aria-valuemin={0}
            aria-valuemax={count - 1}
            aria-valuenow={index}
            aria-valuetext={levels[index]?.label}
            aria-orientation="horizontal"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onKeyDown={onKeyDown}
            className={cn(
              "group/track relative flex h-4 w-full touch-none items-center",
              onSelect && "cursor-pointer",
            )}
          >
            {/* The rail is the full width of the track. It keeps its base colour
                at rest: a rail that only appears on hover reads as an empty
                element until the pointer finds it. */}
            <div className="bg-foreground/10 absolute inset-0 rounded-full" />

            <div
              className="bg-brand absolute h-full rounded-full transition-[width] duration-150"
              style={{
                left: 0,
                width: dotOffset(effortRatio(index, count)),
              }}
            />

            {/* The rungs paint after the fill so they stay countable wherever the
                thumb is. They are surface-coloured with a ring rather than grey:
                a grey dot vanishes into the blue fill, and a blue one vanishes
                into the rail, so neither single colour survives both halves of
                the track. */}
            {levels.map((level, i) => (
              <span
                key={level.key}
                aria-hidden="true"
                // The captions are gone, so the name rides on the dot itself for
                // anyone who wants to know what a rung is called.
                title={level.label}
                className="bg-background ring-foreground/20 absolute size-1 -translate-x-1/2 rounded-full ring-1"
                style={{ left: dotOffset(effortRatio(i, count)) }}
              />
            ))}

            <span
              aria-hidden="true"
              className="bg-brand pointer-events-none absolute size-3.5 -translate-x-1/2 rounded-full border-2 border-background shadow-sm transition-transform group-hover/track:scale-110"
              style={{ left: dotOffset(effortRatio(index, count)) }}
            />
          </div>
        </>
      ) : (
        // One rung is not a choice, so it reads as a readout rather than a
        // control that cannot be moved.
        <div className={cn(field, "rounded-md px-2 py-1.5 text-xs")}>
          {renderLevel ? renderLevel(levels[0]) : levels[0]?.label}
        </div>
      )}
    </div>
  );
}
