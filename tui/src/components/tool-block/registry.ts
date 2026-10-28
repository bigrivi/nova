import { shellRenderer, codeRunRenderer } from "./renderers/shell.ts";
import { readRenderer, readImageRenderer, writeRenderer, editRenderer } from "./renderers/file.ts";
import { globRenderer, grepRenderer } from "./renderers/search.ts";
import { webSearchRenderer, webFetchRenderer } from "./renderers/web.ts";
import { todoRenderer } from "./renderers/todo.ts";
import { SIMPLE_RENDERERS } from "./renderers/simple.ts";
import { createFallbackRenderer } from "./renderers/fallback.ts";
import type { ToolRenderer } from "./types.ts";

/** Erase a renderer's argument type at the single registration point. */
export function defineRenderer<A>(renderer: ToolRenderer<A>): ToolRenderer {
    return renderer as ToolRenderer;
}

type RendererEntry = readonly [name: string, renderer: ToolRenderer];

/**
 * Build the name → renderer table.
 *
 * Args:
 *   entries: Renderers in registration order.
 *
 * Returns:
 *   A map keyed by tool name.
 *
 * Raises:
 *   Error: when two entries share a name, so a spread cannot silently shadow a
 *     dedicated renderer (which is how `read_image` lost its implementation).
 */
export function buildRegistry(
    entries: readonly RendererEntry[],
): Map<string, ToolRenderer> {
    const registry = new Map<string, ToolRenderer>();
    for (const [name, renderer] of entries) {
        if (registry.has(name)) {
            throw new Error(`duplicate tool renderer for "${name}"`);
        }
        registry.set(name, renderer);
    }
    return registry;
}

const ENTRIES: RendererEntry[] = [
    ["shell", defineRenderer(shellRenderer)],
    ["code_run", defineRenderer(codeRunRenderer)],
    ["read", defineRenderer(readRenderer)],
    ["read_image", defineRenderer(readImageRenderer)],
    ["write", defineRenderer(writeRenderer)],
    ["edit", defineRenderer(editRenderer)],
    ["glob", defineRenderer(globRenderer)],
    ["grep", defineRenderer(grepRenderer)],
    ["web_search", defineRenderer(webSearchRenderer)],
    ["web_fetch", defineRenderer(webFetchRenderer)],
    ["todo_write", defineRenderer(todoRenderer)],
    ...Object.entries(SIMPLE_RENDERERS).map(
        ([name, renderer]) => [name, defineRenderer(renderer)] as const,
    ),
];

const RENDERERS = buildRegistry(ENTRIES);

// One fallback per tool name: the subject embeds the name, so they cannot be
// shared, but they must not be rebuilt on every keystroke either.
const FALLBACKS = new Map<string, ToolRenderer>();

export function getRenderer(toolName: string): ToolRenderer {
    const registered = RENDERERS.get(toolName);
    if (registered) return registered;
    const cached = FALLBACKS.get(toolName);
    if (cached) return cached;
    const fallback = createFallbackRenderer(toolName);
    FALLBACKS.set(toolName, fallback);
    return fallback;
}
