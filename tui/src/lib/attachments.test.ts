import { describe, expect, test } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
    MAX_ATTACHMENT_BYTES,
    normalizePastedPath,
    parsePastedPaths,
    readImageAttachment,
    resolvePastedImages,
    toNovaAttachment,
} from "./attachments.ts";

const PNG_BYTES = Buffer.from("89504e470d0a1a0a", "hex");

function tempDir(): string {
    return mkdtempSync(join(tmpdir(), "nova-attach-"));
}

describe("normalizePastedPath", () => {
    test("strips quotes", () => {
        expect(normalizePastedPath('"/tmp/a b.png"', "darwin")).toBe("/tmp/a b.png");
        expect(normalizePastedPath("'/tmp/a.png'", "darwin")).toBe("/tmp/a.png");
    });

    test("decodes a file:// URL", () => {
        expect(normalizePastedPath("file:///tmp/a%20b.png", "darwin")).toBe(
            "/tmp/a b.png",
        );
    });

    test("accepts localhost but refuses a remote host", () => {
        expect(normalizePastedPath("file://localhost/tmp/a.png", "darwin")).toBe(
            "/tmp/a.png",
        );
        expect(normalizePastedPath("file://server/tmp/a.png", "darwin")).toBe(
            "file://server/tmp/a.png",
        );
    });

    test("maps a file:// URL to a Windows path", () => {
        expect(normalizePastedPath("file:///C:/Users/x/a.png", "win32")).toBe(
            "C:\\Users\\x\\a.png",
        );
        expect(normalizePastedPath("file://host/C:/a.png", "win32")).toBe(
            "\\\\host\\C:\\a.png",
        );
    });

    test("unescapes backslashes off Windows", () => {
        expect(normalizePastedPath("/tmp/a\\ b.png", "darwin")).toBe("/tmp/a b.png");
        expect(normalizePastedPath("C:\\a b.png", "win32")).toBe("C:\\a b.png");
    });

    test("keeps CJK paths", () => {
        expect(normalizePastedPath("/tmp/截图 1.png", "darwin")).toBe("/tmp/截图 1.png");
    });
});

describe("parsePastedPaths", () => {
    test("splits on whitespace and newlines", () => {
        expect(parsePastedPaths("/a/1.png\n/a/2.png", "darwin")).toEqual([
            "/a/1.png",
            "/a/2.png",
        ]);
        expect(parsePastedPaths("/a/1.png /a/2.png", "darwin")).toEqual([
            "/a/1.png",
            "/a/2.png",
        ]);
    });

    test("keeps spaces inside quotes", () => {
        expect(parsePastedPaths('"/a/shot 1.png" /b.png', "darwin")).toEqual([
            "/a/shot 1.png",
            "/b.png",
        ]);
    });

    test("decodes file URLs", () => {
        expect(parsePastedPaths("file:///a/1.png\nfile:///a/2.png", "darwin")).toEqual([
            "/a/1.png",
            "/a/2.png",
        ]);
    });

    test("refuses an unbalanced quote", () => {
        expect(parsePastedPaths('"/a/1.png', "darwin")).toEqual([]);
    });
});

describe("readImageAttachment", () => {
    test("reads an image into a data URL", async () => {
        const dir = tempDir();
        const path = join(dir, "shot.png");
        writeFileSync(path, PNG_BYTES);
        const image = await readImageAttachment(path);
        expect(image?.name).toBe("shot.png");
        expect(image?.mime).toBe("image/png");
        expect(image?.dataUrl).toBe(
            `data:image/png;base64,${PNG_BYTES.toString("base64")}`,
        );
    });

    test("is case insensitive about the extension", async () => {
        const dir = tempDir();
        const path = join(dir, "shot.JPEG");
        writeFileSync(path, PNG_BYTES);
        expect((await readImageAttachment(path))?.mime).toBe("image/jpeg");
    });

    test("refuses non-images, missing files and oversized files", async () => {
        const dir = tempDir();
        const text = join(dir, "notes.txt");
        writeFileSync(text, "hello");
        expect(await readImageAttachment(text)).toBeUndefined();
        expect(await readImageAttachment(join(dir, "missing.png"))).toBeUndefined();

        const big = join(dir, "big.png");
        writeFileSync(big, Buffer.alloc(MAX_ATTACHMENT_BYTES + 1));
        expect(await readImageAttachment(big)).toBeUndefined();
    });
});

describe("resolvePastedImages", () => {
    test("returns one image per readable path", async () => {
        const dir = tempDir();
        const first = join(dir, "a.png");
        const second = join(dir, "b.gif");
        writeFileSync(first, PNG_BYTES);
        writeFileSync(second, PNG_BYTES);
        const images = await resolvePastedImages(`${first}\n${second}`, "darwin");
        expect(images?.map((image) => image.name)).toEqual(["a.png", "b.gif"]);
    });

    test("is all-or-nothing: one bad path means plain text", async () => {
        const dir = tempDir();
        const good = join(dir, "a.png");
        writeFileSync(good, PNG_BYTES);
        expect(
            await resolvePastedImages(`${good}\n${join(dir, "notes.txt")}`, "darwin"),
        ).toBeUndefined();
    });

    test("declines prose", async () => {
        expect(await resolvePastedImages("hello there", "darwin")).toBeUndefined();
    });
});

describe("toNovaAttachment", () => {
    test("matches the backend contract", async () => {
        const dir = tempDir();
        const path = join(dir, "shot.png");
        writeFileSync(path, PNG_BYTES);
        const image = (await readImageAttachment(path))!;
        const attachment = toNovaAttachment(image);
        expect(attachment.type).toBe("image");
        expect(attachment.name).toBe("shot.png");
        expect(attachment.contentType).toBe("image/png");
        expect(attachment.content).toEqual([
            { type: "image", image: image.dataUrl },
        ]);
        expect(attachment.id).not.toBe(toNovaAttachment(image).id);
    });
});
