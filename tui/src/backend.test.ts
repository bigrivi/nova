import { afterEach, describe, expect, test } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Readable } from "node:stream";
import {
    isListening,
    parseRegistration,
    readAnnouncement,
    readRegistration,
} from "./backend.ts";

function home_with(record: unknown): string {
    const home = mkdtempSync(join(tmpdir(), "nova-registration-"));
    writeFileSync(join(home, "server.json"), JSON.stringify(record), "utf-8");
    return home;
}

const original = process.env.NOVA_HOME;

afterEach(() => {
    if (original === undefined) delete process.env.NOVA_HOME;
    else process.env.NOVA_HOME = original;
});

describe("parseRegistration", () => {
    test("keeps an address and the process behind it", () => {
        expect(
            parseRegistration({ url: "http://127.0.0.1:51914", pid: 4242 }),
        ).toEqual({ url: "http://127.0.0.1:51914", pid: 4242 });
    });

    test("rejects a record without an address", () => {
        expect(parseRegistration({ pid: 4242 })).toBeNull();
    });

    test("rejects a record without a usable process id", () => {
        expect(parseRegistration({ url: "http://127.0.0.1:51914", pid: 0 }))
            .toBeNull();
        expect(parseRegistration({ url: "http://127.0.0.1:51914" })).toBeNull();
    });

    test("rejects anything that is not a record", () => {
        expect(parseRegistration(null)).toBeNull();
        expect(parseRegistration("http://127.0.0.1:51914")).toBeNull();
    });
});

describe("readRegistration", () => {
    test("reads the record written by the backend", () => {
        const home = home_with({ url: "http://127.0.0.1:51914", pid: 4242 });

        expect(readRegistration(home)).toEqual({
            url: "http://127.0.0.1:51914",
            pid: 4242,
        });
    });

    test("reads nothing when the backend never recorded itself", () => {
        expect(readRegistration(join(tmpdir(), "nova-registration-absent")))
            .toBeNull();
    });
});

describe("readAnnouncement", () => {
    test("reads the address from the line the backend prints", async () => {
        const stdout = Readable.from([
            '{"url":"http://127.0.0.1:51914"}\n',
        ]);

        expect(await readAnnouncement(stdout, 1_000)).toBe(
            "http://127.0.0.1:51914",
        );
    });

    test("reads an address split across two chunks", async () => {
        const stdout = Readable.from([
            '{"url":"http://127.0.0.1:',
            '51914"}\n',
        ]);

        expect(await readAnnouncement(stdout, 1_000)).toBe(
            "http://127.0.0.1:51914",
        );
    });

    test("reads nothing when the backend exits without announcing", async () => {
        const stdout = Readable.from([]);

        expect(await readAnnouncement(stdout, 1_000)).toBeNull();
    });

    test("reads nothing when the line is not an address", async () => {
        const stdout = Readable.from(["Starting Nova backend...\n"]);

        expect(await readAnnouncement(stdout, 1_000)).toBeNull();
    });

    test("gives up rather than waiting forever on a silent backend", async () => {
        const stdout = new Readable({ read() {} });

        expect(await readAnnouncement(stdout, 10)).toBeNull();
    });
});

describe("isListening", () => {
    test("finds a backend that is accepting connections", async () => {
        const listener = Bun.listen({
            hostname: "127.0.0.1",
            port: 0,
            socket: { data() {} },
        });
        try {
            expect(
                await isListening(`http://127.0.0.1:${listener.port}`),
            ).toBe(true);
        } finally {
            listener.stop(true);
        }
    });

    test("reports a port nobody holds as dead", async () => {
        expect(await isListening("http://127.0.0.1:1", 200)).toBe(false);
    });

    test("does not believe an address it cannot parse", async () => {
        expect(await isListening("not an address")).toBe(false);
    });
});
