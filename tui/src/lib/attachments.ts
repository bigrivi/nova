/** Local files pasted into the composer.
 *
 *  Terminals deliver a dragged file as a bracketed paste of its path (macOS
 *  Finder sends a `file://` URL), so this module owns the two questions the
 *  composer has to answer: which path did the user mean, and is it an image the
 *  model can read?
 */
import { basename, extname, isAbsolute, relative } from "node:path";
import type { NovaAttachmentData } from "../api/types.ts";
import { WORKSPACE_DIR } from "../workspace.ts";

/** Same ceiling the backend enforces for one image. */
export const MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024;

/** Bound the filesystem work one paste can trigger. */
const MAX_PASTED_PATHS = 32;

const IMAGE_MIME: Record<string, string> = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
};

/** A pasted path the composer kept: an image, or a file it only references. */
export type PastedFile = {
    path: string;
    name: string;
    kind: "image" | "file";
    /** Present for images: the decoded payload the request carries. */
    image?: LocalImage;
};

export type LocalImage = {
    path: string;
    name: string;
    mime: string;
    /** `data:<mime>;base64,…`, the shape the backend attachment carries. */
    dataUrl: string;
};

function decodeFileUrl(value: string, platform: string): string | undefined {
    if (!value.startsWith("file://")) return undefined;
    try {
        const url = new URL(value);
        if (/%2f|%5c/i.test(url.pathname)) return undefined;
        const pathname = decodeURIComponent(url.pathname);
        if (platform !== "win32") {
            if (url.hostname && url.hostname !== "localhost") return undefined;
            return pathname;
        }
        const local = pathname.replace(/^\/([A-Za-z]:)/, "$1").replaceAll("/", "\\");
        if (url.hostname && url.hostname !== "localhost") {
            const separator = local.startsWith("\\") ? "" : "\\";
            return `\\\\${url.hostname}${separator}${local}`;
        }
        return local;
    } catch {
        return undefined;
    }
}

/**
 * Turn one pasted token into a filesystem path.
 *
 * Args:
 *   value: A path, a quoted path, or a `file://` URL from a file manager.
 *   platform: `process.platform`, injectable for tests.
 *
 * Returns:
 *   The path with quotes and `file://` decoration removed.
 */
export function normalizePastedPath(
    value: string,
    platform: string = process.platform,
): string {
    const raw = value.trim().replace(/^['"]+|['"]+$/g, "");
    const url = decodeFileUrl(raw, platform);
    if (url) return url;
    if (platform === "win32") return raw;
    return raw.replace(/\\(.)/g, "$1");
}

/**
 * Split a paste into candidate paths.
 *
 * Args:
 *   value: Pasted text, possibly several newline- or space-separated paths.
 *   platform: `process.platform`, injectable for tests.
 *
 * Returns:
 *   Normalised paths; quoted segments keep their spaces. Empty when the paste
 *   cannot be read as a path list.
 */
export function parsePastedPaths(
    value: string,
    platform: string = process.platform,
): string[] {
    const paths: string[] = [];
    let current = "";
    let quote = "";

    const push = () => {
        if (!current) return;
        paths.push(decodeFileUrl(current, platform) ?? current);
        current = "";
    };

    for (let index = 0; index < value.length; index++) {
        const character = value[index]!;
        if (quote) {
            if (character === quote) {
                quote = "";
                continue;
            }
            if (character === "\\" && platform !== "win32" && index + 1 < value.length) {
                current += value[++index];
                continue;
            }
            current += character;
            continue;
        }
        if (character === "'" || character === '"') {
            quote = character;
            continue;
        }
        if (character === "\\" && platform !== "win32" && index + 1 < value.length) {
            current += value[++index];
            continue;
        }
        if (/\s/.test(character)) {
            push();
            if (paths.length > MAX_PASTED_PATHS) return [];
            continue;
        }
        current += character;
    }
    if (quote) return [];
    push();
    return paths.length > MAX_PASTED_PATHS ? [] : paths;
}

/**
 * Read a pasted path as an image attachment.
 *
 * Args:
 *   path: Filesystem path (already normalised).
 *
 * Returns:
 *   The image, or undefined when the file is missing, is not an image, or is
 *   larger than the budget — callers then fall back to inserting the path.
 */
export async function readImageAttachment(
    path: string,
): Promise<LocalImage | undefined> {
    const mime = IMAGE_MIME[extname(path).toLowerCase()];
    if (!mime) return undefined;
    const file = Bun.file(path);
    if (!(await file.exists())) return undefined;
    if (file.size > MAX_ATTACHMENT_BYTES) return undefined;
    const bytes = new Uint8Array(await file.arrayBuffer());
    return {
        path,
        name: basename(path),
        mime,
        dataUrl: `data:${mime};base64,${Buffer.from(bytes).toString("base64")}`,
    };
}

/**
 * Readable form of a path: relative when it lives in the workspace, absolute
 * otherwise, so the model gets a path its tools can resolve and logs do not
 * carry the whole home directory.
 */
export function displayPath(path: string): string {
    const rel = relative(WORKSPACE_DIR, path);
    if (!rel || rel.startsWith("..") || isAbsolute(rel)) return path;
    return rel;
}

/**
 * Resolve a paste into files the composer can keep.
 *
 * Args:
 *   text: Pasted text, possibly several paths.
 *   platform: `process.platform`, injectable for tests.
 *
 * Returns:
 *   One entry per path, or undefined when any path is missing (prose, a typo, a
 *   half-copied list) — the composer then inserts the text unchanged.
 */
export async function resolvePastedFiles(
    text: string,
    platform: string = process.platform,
): Promise<PastedFile[] | undefined> {
    const paths = parsePastedPaths(text.trim(), platform);
    if (paths.length === 0) return undefined;
    const files: PastedFile[] = [];
    for (const path of paths) {
        const image = await readImageAttachment(path);
        if (image) {
            files.push({ path, name: image.name, kind: "image", image });
            continue;
        }
        if (!(await Bun.file(path).exists())) return undefined;
        files.push({ path, name: basename(path), kind: "file" });
    }
    return files;
}

let nextAttachmentId = 0;

/** Shape one image as the backend's attachment payload. */
export function toNovaAttachment(image: LocalImage): NovaAttachmentData {
    nextAttachmentId += 1;
    return {
        id: `tui-${nextAttachmentId}`,
        type: "image",
        name: image.name,
        contentType: image.mime,
        content: [{ type: "image", image: image.dataUrl }],
    };
}
