import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { preferencePath, readPreference, writePreference } from "./preference.ts";

const originalHome = process.env.NOVA_HOME;
let home = "";

beforeEach(() => {
    home = mkdtempSync(join(tmpdir(), "nova-theme-"));
    process.env.NOVA_HOME = home;
});

afterEach(() => {
    if (originalHome === undefined) delete process.env.NOVA_HOME;
    else process.env.NOVA_HOME = originalHome;
});

describe("theme preference", () => {
    test("round-trips a known theme", () => {
        writePreference("palenight");
        expect(readPreference()).toBe("palenight");
    });

    test("round-trips system", () => {
        writePreference("system");
        expect(readPreference()).toBe("system");
    });

    test("falls back to system when the file is missing", () => {
        expect(readPreference()).toBe("system");
    });

    test("falls back to system for an unknown theme", () => {
        writeFileSync(
            preferencePath(),
            JSON.stringify({ preference: "not-a-theme" }),
        );
        expect(readPreference()).toBe("system");
    });

    test("falls back to system for malformed JSON", () => {
        writeFileSync(preferencePath(), "{");
        expect(readPreference()).toBe("system");
    });

    test("reads under NOVA_HOME", () => {
        expect(preferencePath()).toBe(join(home, "tui-theme.json"));
    });
});
