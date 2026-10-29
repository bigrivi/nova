/** `@`-mention completion: the token being typed, and the paths it could mean.
 *
 *  Reads the local disk directly, the same way pasted files are resolved: the
 *  TUI is a local process, so asking the backend for every keystroke would add
 *  a round trip to the loop that most needs to stay instant.
 */
import { readdir } from "node:fs/promises";
import { isAbsolute, join } from "node:path";

const MAX_ITEMS = 20;

export type MentionToken = {
    /** Index of the `@` in the composer text. */
    start: number;
    /** What follows it, possibly a partial path such as `src/comp`. */
    query: string;
};

export type FileCandidate = {
    /** Text inserted after the `@`; directories keep a trailing slash. */
    insert: string;
    isDir: boolean;
};

/** The `@` token being typed at the end of *text*, or null when there is none. */
export function activeMention(text: string): MentionToken | null {
    const match = /(^|\s)@(\S*)$/.exec(text);
    if (!match) return null;
    return { start: (match.index ?? 0) + (match[1]?.length ?? 0), query: match[2] ?? "" };
}

/** Split a query into the directory part (with trailing slash) and name prefix. */
function splitQuery(query: string): { dirPart: string; namePrefix: string } {
    const slash = Math.max(query.lastIndexOf("/"), query.lastIndexOf("\\"));
    if (slash < 0) return { dirPart: "", namePrefix: query };
    return { dirPart: query.slice(0, slash + 1), namePrefix: query.slice(slash + 1) };
}

/**
 * Candidate paths for a mention query, directories first.
 *
 * A relative query resolves against *cwd*; an unreadable directory yields an
 * empty list rather than an error, because a half-typed path is the normal
 * state of the input this runs on.
 */
export async function completeMentions(
    query: string,
    cwd: string,
): Promise<FileCandidate[]> {
    const { dirPart, namePrefix } = splitQuery(query);
    const directory = isAbsolute(dirPart) ? dirPart || "/" : join(cwd, dirPart);

    let entries;
    try {
        entries = await readdir(directory, { withFileTypes: true });
    } catch {
        return [];
    }

    const prefix = namePrefix.toLowerCase();
    return entries
        .filter((entry) => entry.isDirectory() || entry.isFile())
        // A prefix that names a dotfile is the only way to see dotfiles.
        .filter((entry) => !entry.name.startsWith(".") || prefix.startsWith("."))
        .filter((entry) => entry.name.toLowerCase().startsWith(prefix))
        .sort(
            (left, right) =>
                Number(right.isDirectory()) - Number(left.isDirectory()) ||
                left.name.localeCompare(right.name),
        )
        .slice(0, MAX_ITEMS)
        .map((entry) => ({
            insert: `${dirPart}${entry.name}${entry.isDirectory() ? "/" : ""}`,
            isDir: entry.isDirectory(),
        }));
}
