/**
 * Bridge configuration, resolved once from the environment.
 */

import { homedir } from "node:os";
import { join } from "node:path";
import { DEFAULT_OUTBOX_DIR } from "./outbox.js";

/** Everything the bridge needs to talk to Nova and shape WeChat replies. */
export interface BridgeConfig {
  /** Nova HTTP base URL. Loopback by default, where Nova's Basic auth is exempt. */
  readonly novaBaseUrl: string;
  /** Nova agent key that runs WeChat turns. */
  readonly agentKey: string;
  /** Workspace root handed to Nova; defaults to the bridge's working directory. */
  readonly workspaceDir: string;
  /** Minimum gap between progress bubbles. WeChat cannot edit a sent message. */
  readonly progressIntervalMs: number;
  /** Cap on a single reply before the overflow spills into a file attachment. */
  readonly maxTextChars: number;
  /** Where `conversationId -> sessionId` bindings are persisted. */
  readonly statePath: string;
  /** Directory for spilled long replies. */
  readonly spillDir: string;
  /** Directory an agent drops files into to have them sent. */
  readonly outboxDir: string;
  /**
   * Extra directories files may be sent from.
   *
   * Deliberately separate from `workspaceDir`: widening what can leave the
   * machine must not widen what the agent itself can read or write.
   */
  readonly sendRoots: readonly string[];
  /** Largest file that may leave the machine, in bytes. */
  readonly maxFileBytes: number;
  /** Hold an idle-sleep assertion for the bridge's lifetime. */
  readonly keepAwake: boolean;
  /** Silence before a still-working notice is pushed, in milliseconds. */
  readonly stillWorkingMs: number;
  /** Optional Basic credentials, needed only when Nova is not on loopback. */
  readonly authUser?: string;
  readonly authPassword?: string;
}

/** Read a non-empty string variable, or fall back when unset/blank. */
function readString(name: string, fallback: string): string {
  const raw = process.env[name]?.trim();
  return raw ? raw : fallback;
}

/** Read a positive integer variable, or fall back when unset or unparseable. */
function readPositiveInt(name: string, fallback: number): number {
  const raw = process.env[name]?.trim();
  if (!raw) {
    return fallback;
  }
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

/** Read a boolean variable, where only an explicit truthy value counts. */
function readFlag(name: string): boolean {
  const raw = process.env[name]?.trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
}

/**
 * Read a path list, accepting `:` or `,` separators and `~` expansion.
 *
 * `NOVA_SEND_ROOTS` is how a user opts a directory in for sending without
 * handing the agent filesystem access to it.
 */
function readPathList(name: string): readonly string[] {
  const raw = process.env[name];
  if (raw === undefined || !raw.trim()) {
    return [];
  }
  return raw
    .split(/[:,]/)
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0)
    .map((entry) =>
      entry === "~"
        ? homedir()
        : entry.startsWith("~/")
          ? join(homedir(), entry.slice(2))
          : entry,
    );
}

/** Strip any trailing slashes so path joins stay predictable. */
function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

/**
 * Build the configuration from `process.env`.
 *
 * `NOVA_BASE_URL` points at a `nova serve` instance; the bridge never starts
 * Nova itself, so an unreachable URL is a configuration error, not a runtime
 * condition to retry.
 */
export function loadConfig(): BridgeConfig {
  const novaBaseUrl = trimTrailingSlash(
    readString("NOVA_BASE_URL", "http://127.0.0.1:8765"),
  );
  const authUser = process.env.NOVA_AUTH_USER?.trim();
  const authPassword = process.env.NOVA_AUTH_PASSWORD ?? "";
  const config: BridgeConfig = {
    novaBaseUrl,
    agentKey: readString("NOVA_AGENT_KEY", "main"),
    workspaceDir: readString("NOVA_WORKSPACE_DIR", process.cwd()),
    progressIntervalMs: readPositiveInt("NOVA_PROGRESS_INTERVAL_MS", 4000),
    maxTextChars: readPositiveInt("NOVA_MAX_TEXT_CHARS", 4000),
    statePath: readString(
      "NOVA_BRIDGE_STATE",
      join(homedir(), ".nova", "weixin-bridge", "sessions.json"),
    ),
    spillDir: readString(
      "NOVA_BRIDGE_SPILL_DIR",
      join(homedir(), ".nova", "weixin-bridge", "out"),
    ),
    outboxDir: readString("NOVA_BRIDGE_OUTBOX", DEFAULT_OUTBOX_DIR),
    sendRoots: readPathList("NOVA_SEND_ROOTS"),
    maxFileBytes: readPositiveInt("NOVA_MAX_FILE_MB", 100) * 1024 * 1024,
    keepAwake: readFlag("NOVA_KEEP_AWAKE"),
    stillWorkingMs: readPositiveInt("NOVA_STILL_WORKING_MS", 8000),
  };
  return authUser
    ? { ...config, authUser, authPassword }
    : config;
}