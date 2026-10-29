import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { activeMention, completeMentions } from "./file-completion.ts";

describe("activeMention", () => {
    test("finds a token at the end of the text", () => {
        expect(activeMention("read @src/co")).toEqual({
            start: 5,
            query: "src/co",
        });
    });

    test("finds a bare @", () => {
        expect(activeMention("@")).toEqual({ start: 0, query: "" });
    });

    test("ignores a token in the middle of the text", () => {
        expect(activeMention("@src/main.ts please")).toBeNull();
    });

    test("ignores an email", () => {
        expect(activeMention("mail me at a@b")).toBeNull();
    });

    test("has no token without @", () => {
        expect(activeMention("plain text")).toBeNull();
    });
});

describe("completeMentions", () => {
    let root = "";

    beforeAll(async () => {
        root = await mkdtemp(join(tmpdir(), "nova-completion-"));
        await mkdir(join(root, "src"));
        await mkdir(join(root, "scripts"));
        await writeFile(join(root, "README.md"), "");
        await writeFile(join(root, "package.json"), "");
        await writeFile(join(root, ".env"), "");
        await writeFile(join(root, "src", "main.ts"), "");
    });

    afterAll(async () => {
        await rm(root, { recursive: true, force: true });
    });

    test("lists directories before files", async () => {
        const items = await completeMentions("", root);
        expect(items.slice(0, 2).map((item) => item.insert)).toEqual([
            "scripts/",
            "src/",
        ]);
    });

    test("filters by prefix", async () => {
        const items = await completeMentions("sc", root);
        expect(items.map((item) => item.insert)).toEqual(["scripts/"]);
    });

    test("hides dotfiles unless asked for", async () => {
        expect(await completeMentions("", root)).not.toContainEqual(
            expect.objectContaining({ insert: ".env" }),
        );
        expect((await completeMentions(".e", root))[0]?.insert).toBe(".env");
    });

    test("descends into a directory and keeps the prefix on insert", async () => {
        const items = await completeMentions("src/ma", root);
        expect(items[0]?.insert).toBe("src/main.ts");
    });

    test("returns nothing for a directory that does not exist", async () => {
        expect(await completeMentions("nope/x", root)).toEqual([]);
    });
});
