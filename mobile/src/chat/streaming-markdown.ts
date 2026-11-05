/**
 * Incremental Markdown splitting for a streaming message.
 *
 * The naive approach — re-parse the whole message on every token — is O(n²)
 * and re-lays-out every finished block. This splits the growing text into:
 *
 * - `blocks`: complete blocks before the last safe boundary. Their content can
 *   no longer change, so the renderer parses each one once and memoizes it.
 * - `tail`: the block still being written. A paragraph is rendered as plain
 *   text; an open code fence is rendered as a code shell, so the user still
 *   sees monospace immediately and the header/copy/highlight appear when the
 *   fence closes.
 *
 * Safe boundaries are blank lines outside a fenced code block, and the closing
 * line of a fence. A fence can interrupt a paragraph, so the paragraph before
 * it is emitted as its own block.
 *
 * This is a streaming approximation on purpose. Loose lists and tables that
 * span a blank line can split into two blocks until the turn finishes; the
 * final, non-streaming render parses the whole message and fixes the join.
 * That is cheaper than making the splitter a full CommonMark parser, and the
 * difference only exists while text is arriving.
 */

export type MarkdownTail =
    | { kind: "text"; raw: string }
    | { kind: "code"; raw: string; language: string | null };

export type StreamingMarkdown = {
    blocks: string[];
    tail: MarkdownTail;
};

type FenceOpen = {
    char: "`" | "~";
    length: number;
    info: string;
};

function readFenceOpen(line: string): FenceOpen | null {
    const match = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    if (!match) {
        return null;
    }
    const marker = match[1]!;
    return {
        char: marker[0] as "`" | "~",
        length: marker.length,
        info: match[2]!.trim(),
    };
}

function isFenceClose(
    line: string,
    char: "`" | "~",
    length: number,
): boolean {
    const match = line.match(/^ {0,3}(`{3,}|~{3,})\s*$/);
    if (!match) {
        return false;
    }
    const marker = match[1]!;
    return marker[0] === char && marker.length >= length;
}

function languageOf(info: string): string | null {
    const first = info.split(/\s+/)[0] ?? "";
    return first.length > 0 ? first : null;
}

/** Normalise line endings without changing visible content. */
function normalise(text: string): string {
    return text.replace(/\r\n?/g, "\n");
}

export function splitStreamingMarkdown(text: string): StreamingMarkdown {
    const source = normalise(text);
    const lines = source.split("\n");
    const blocks: string[] = [];

    const push = (from: number, to: number) => {
        if (to <= from) {
            return;
        }
        const raw = lines
            .slice(from, to)
            .join("\n")
            .replace(/\n+$/, "");
        if (raw.trim().length > 0) {
            blocks.push(raw);
        }
    };

    let blockStart = 0;
    let fenceStart = -1;
    let fence: FenceOpen | null = null;

    for (let index = 0; index < lines.length; index += 1) {
        const line = lines[index]!;

        if (fence !== null) {
            if (isFenceClose(line, fence.char, fence.length)) {
                push(fenceStart, index + 1);
                fence = null;
                fenceStart = -1;
                blockStart = index + 1;
            }
            continue;
        }

        const opened = readFenceOpen(line);
        if (opened !== null) {
            // A fence may interrupt a paragraph: close the paragraph first.
            push(blockStart, index);
            fence = opened;
            fenceStart = index;
            blockStart = index;
            continue;
        }

        if (line.trim() === "") {
            push(blockStart, index);
            blockStart = index + 1;
        }
    }

    if (fence !== null) {
        return {
            blocks,
            tail: {
                kind: "code",
                raw: lines.slice(fenceStart).join("\n"),
                language: languageOf(fence.info),
            },
        };
    }

    return {
        blocks,
        tail: {
            kind: "text",
            raw: lines.slice(blockStart).join("\n").replace(/\n+$/, ""),
        },
    };
}
