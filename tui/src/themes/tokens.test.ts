import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { themes } from "./index.ts";

const SOURCE_ROOT = join(import.meta.dir, "..");
const SKIP = new Set(["themes"]);

/** Every dotted leaf path in a theme object, e.g. "text.muted". */
function leafPaths(value: unknown, prefix = ""): string[] {
    if (typeof value === "string") return [prefix];
    if (value === null || typeof value !== "object") return [];
    return Object.entries(value).flatMap(([key, inner]) =>
        leafPaths(inner, prefix ? `${prefix}.${key}` : key),
    );
}

/** Token paths the TUI actually asks for, e.g. "primary.base". */
function referencedPaths(): Set<string> {
    const found = new Set<string>();
    const walk = (directory: string): void => {
        for (const entry of Array.from(
            new Bun.Glob("**/*.{ts,tsx}").scanSync({ cwd: directory }),
        )) {
            const top = entry.split("/")[0]!;
            if (SKIP.has(top) || entry.includes(".test.")) continue;
            const source = readFileSync(join(directory, entry), "utf8");
            for (const match of source.matchAll(
                /\btheme\.([a-z]+(?:\.[a-zA-Z]+)+)/g,
            )) {
                found.add(match[1]!);
            }
        }
    };
    walk(SOURCE_ROOT);
    return found;
}

describe("theme tokens", () => {
    const referenced = referencedPaths();

    test("every token is consumed somewhere", () => {
        // a token nobody reads is a token nobody maintains (surfaceDeep was one)
        const unused = leafPaths(themes.dark).filter(
            (path) => !referenced.has(path),
        );
        expect(unused).toEqual([]);
    });

    test("every path the TUI asks for exists in every theme", () => {
        for (const [name, palette] of Object.entries(themes)) {
            const paths = new Set(leafPaths(palette));
            const missing = [...referenced].filter((path) => !paths.has(path));
            expect({ name, missing }).toMatchObject({ name });
            expect({ name, missing }).toMatchObject({ missing: [] });
        }
    });
});
