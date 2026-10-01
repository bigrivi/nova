/**
 * Outbound files: validating what may leave the machine, and draining the outbox.
 *
 * A chat surface is an exfiltration path, so nothing is sent just because a path
 * appeared in a conversation. Every candidate must pass `resolveSendable`, which
 * confines it to an allowed root and rejects anything that is not a plain
 * readable file.
 */

import { stat, readdir, unlink } from "node:fs/promises";
import { realpathSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { error, info, warn } from "./log.js";

/** Default directory an agent drops files into to have them sent. */
export const DEFAULT_OUTBOX_DIR = join(homedir(), ".nova", "weixin-bridge", "outbox");

/** Refusal reasons, phrased for a chat bubble. */
export type Refusal =
  | "empty-path"
  | "not-absolute"
  | "outside-allowed-roots"
  | "not-found"
  | "not-a-file"
  | "too-large";

/** Outcome of validating one candidate path. */
export type Resolution =
  | { readonly ok: true; readonly path: string; readonly name: string; readonly bytes: number }
  | { readonly ok: false; readonly reason: Refusal; readonly detail: string };

/** Why something was refused, in the user's language. */
export function explainRefusal(refusal: Refusal, detail: string): string {
  switch (refusal) {
    case "empty-path":
      return "用法：/send <文件路径>";
    case "not-absolute":
      return `需要绝对路径，收到的是 ${detail}`;
    case "outside-allowed-roots":
      return `${detail} 不在允许发送的目录内，已拒绝`;
    case "not-found":
      return `文件不存在：${detail}`;
    case "not-a-file":
      return `不是普通文件：${detail}`;
    case "too-large":
      return `文件太大：${detail}`;
  }
}

/** True when `candidate` is `root` or lives under it. */
function withinRoot(candidate: string, root: string): boolean {
  const rel = relative(root, candidate);
  return rel === "" || (!rel.startsWith(`..${sep}`) && rel !== ".." && !isAbsolute(rel));
}

/**
 * Resolve a root to its real path.
 *
 * The candidate is realpath'd before comparison, so the root must be too: on
 * macOS `/var` and `/tmp` are symlinks into `/private`, and comparing a resolved
 * candidate against an unresolved root makes every legitimate path look foreign.
 */
function resolveRoot(root: string): string {
  try {
    return realpathSync(root);
  } catch {
    // A root that does not exist yet cannot contain anything.
    return resolve(root);
  }
}

/**
 * Validate one path against the allowed roots.
 *
 * Symlinks are resolved before the containment check, so a link inside an
 * allowed root cannot point out of it. Directories are refused: sending one has
 * no meaning over this channel and would hide how much is being exposed.
 */
export async function resolveSendable(
  rawPath: string,
  roots: readonly string[],
  maxBytes: number,
): Promise<Resolution> {
  const trimmed = rawPath.trim().replace(/^["']|["']$/g, "");
  if (!trimmed) {
    return { ok: false, reason: "empty-path", detail: "" };
  }
  if (!isAbsolute(trimmed)) {
    return { ok: false, reason: "not-absolute", detail: trimmed };
  }

  // realpath collapses symlinks and `..` before the root comparison.
  let real: string;
  try {
    real = await realpathOrSelf(trimmed);
  } catch (cause) {
    warn("send target unreadable", trimmed, String(cause));
    return { ok: false, reason: "not-found", detail: trimmed };
  }

  if (!roots.some((root) => withinRoot(real, resolveRoot(root)))) {
    return { ok: false, reason: "outside-allowed-roots", detail: trimmed };
  }

  let stats;
  try {
    stats = await stat(real);
  } catch {
    return { ok: false, reason: "not-found", detail: trimmed };
  }
  if (!stats.isFile()) {
    return { ok: false, reason: "not-a-file", detail: trimmed };
  }
  if (stats.size > maxBytes) {
    return {
      ok: false,
      reason: "too-large",
      detail: `${(stats.size / 1024 / 1024).toFixed(1)}MB，上限 ${(maxBytes / 1024 / 1024).toFixed(0)}MB`,
    };
  }

  return {
    ok: true,
    path: real,
    name: real.split(sep).pop() ?? real,
    bytes: stats.size,
  };
}

/**
 * Resolve a path that may not exist yet.
 *
 * A missing leaf still has to be resolved through its parent, otherwise the
 * result keeps any symlinked prefix (`/var` vs `/private/var` on macOS) and the
 * containment check then rejects a legitimate path as foreign.
 */
async function realpathOrSelf(path: string): Promise<string> {
  const { realpath } = await import("node:fs/promises");
  try {
    return await realpath(path);
  } catch (cause) {
    if ((cause as NodeJS.ErrnoException).code !== "ENOENT") {
      throw cause;
    }
  }
  const parent = dirname(path);
  const leaf = basename(path);
  try {
    return join(await realpath(parent), leaf);
  } catch {
    return resolve(path);
  }
}

/** Create the outbox if needed and return it. */
export async function ensureOutbox(dir: string): Promise<string> {
  const { mkdir } = await import("node:fs/promises");
  await mkdir(dir, { recursive: true });
  return dir;
}

/** Files sitting in the outbox, oldest first. */
export async function listOutbox(dir: string): Promise<readonly string[]> {
  let entries: string[];
  try {
    entries = await readdir(dir);
  } catch (cause) {
    if ((cause as NodeJS.ErrnoException).code === "ENOENT") {
      return [];
    }
    error("outbox unreadable", dir, String(cause));
    return [];
  }
  return entries
    .filter((name) => !name.startsWith("."))
    .sort()
    .map((name) => join(dir, name));
}

/** Remove a file from the outbox after it has been sent. */
export async function consumeOutboxFile(dir: string, path: string): Promise<void> {
  try {
    await unlink(path);
  } catch (cause) {
    warn("could not remove sent outbox file", path, String(cause));
  }
}