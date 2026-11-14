import { afterEach, describe, expect, test } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { backendPort, DEFAULT_API_PORT } from "./port.ts";

function home_with(config: unknown): string {
    const home = mkdtempSync(join(tmpdir(), "nova-port-"));
    writeFileSync(
        join(home, "config.json"),
        JSON.stringify(config),
        "utf-8",
    );
    return home;
}

const original = process.env.NOVA_HOME;

afterEach(() => {
    if (original === undefined) delete process.env.NOVA_HOME;
    else process.env.NOVA_HOME = original;
});

describe("backendPort", () => {
    test("reads the port the configuration names", () => {
        // The backend binds this port, so the client has to ask for the same
        // one: asking the default while the server listens elsewhere leaves
        // every screen saying "Unable to connect".
        process.env.NOVA_HOME = home_with({ server: { port: 51999 } });

        expect(backendPort()).toBe(51999);
    });

    test("accepts a port written as a string", () => {
        process.env.NOVA_HOME = home_with({ server: { port: "51999" } });

        expect(backendPort()).toBe(51999);
    });

    test("falls back when the configuration names no port", () => {
        process.env.NOVA_HOME = home_with({});

        expect(backendPort()).toBe(DEFAULT_API_PORT);
    });

    test("falls back on a port that is not one", () => {
        process.env.NOVA_HOME = home_with({ server: { port: "not a port" } });

        expect(backendPort()).toBe(DEFAULT_API_PORT);
    });

    test("falls back when there is no configuration at all", () => {
        process.env.NOVA_HOME = join(tmpdir(), "nova-port-does-not-exist");

        expect(backendPort()).toBe(DEFAULT_API_PORT);
    });
});
