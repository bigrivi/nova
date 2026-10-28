import { describe, expect, test } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
    displayPath,
    MAX_ATTACHMENT_BYTES,
    normalizePastedPath,
    parsePastedPaths,
    readImageAttachment,
    resolvePastedFiles,
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

describe("resolvePastedFiles", () => {
    test("marks images and plain files differently", async () => {
        const dir = tempDir();
        const image = join(dir, "a.png");
        const text = join(dir, "notes.md");
        writeFileSync(image, PNG_BYTES);
        writeFileSync(text, "# hi");
        const files = await resolvePastedFiles(`${image}\n${text}`, "darwin");
        expect(files?.map((file) => [file.name, file.kind])).toEqual([
            ["a.png", "image"],
            ["notes.md", "file"],
        ]);
        expect(files?.[0]?.image?.mime).toBe("image/png");
        expect(files?.[1]?.image).toBeUndefined();
    });

    test("is all-or-nothing: one missing path means plain text", async () => {
        const dir = tempDir();
        const good = join(dir, "a.png");
        writeFileSync(good, PNG_BYTES);
        expect(
            await resolvePastedFiles(`${good}\n${join(dir, "missing.txt")}`, "darwin"),
        ).toBeUndefined();
    });

    test("declines prose", async () => {
        expect(await resolvePastedFiles("hello there", "darwin")).toBeUndefined();
    });

    test("a file over the image budget is still a reference", async () => {
        const dir = tempDir();
        const big = join(dir, "big.png");
        writeFileSync(big, Buffer.alloc(MAX_ATTACHMENT_BYTES + 1));
        const files = await resolvePastedFiles(big, "darwin");
        expect(files?.[0]?.kind).toBe("file");
    });
});

describe("displayPath", () => {
    test("keeps paths outside the workspace absolute", () => {
        expect(displayPath("/definitely/not/in/the/workspace/x.ts")).toBe(
            "/definitely/not/in/the/workspace/x.ts",
        );
    });

    test("makes workspace paths relative", () => {
        const inside = join(process.cwd(), "src", "lib", "attachments.ts");
        expect(displayPath(inside)).toBe("src/lib/attachments.ts");
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
