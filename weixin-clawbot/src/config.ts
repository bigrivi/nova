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
  /**
   * The agent a conversation starts on, before any `/agent` switch.
   *
   * Also this bridge's own namespace: its sessions live in `sessions.json` and
   * its outbox is the base directory, so the agents reachable through `/agent`
   * are kept apart underneath it.
   */
  readonly agentKey: string;
  /** Workspace root handed to Nova; defaults to the bridge's working directory. */
  readonly workspaceDir: string;
  /** Minimum gap between progress bubbles. WeChat cannot edit a sent message. */
  readonly progressIntervalMs: number;
  /** Cap on a single reply before the overflow spills into a file attachment. */
  readonly maxTextChars: number;
  /** Where `conversationId -> sessionId` bindings are persisted. */
  readonly statePath: string;
  /** Which agent each conversation selected with `/agent`. */
  readonly currentAgentPath: string;
  /** Which WeChat bot this bridge serves. */
  readonly accountPath: string;
  /**
   * The file an earlier per-agent layout wrote, consulted only to recognise it.
   *
   * That layout recorded one bot per Nova agent, which WeChat does not allow, so
   * there is nothing to migrate: it is read to warn that a rescan is the way to
   * be sure which bot is live.
   */
  readonly legacyAccountPath: string;
  /** Directory for spilled long replies. */
  readonly spillDir: string;
  /**
   * Base directory agents drop files into to have them sent.
   *
   * Each agent gets a subdirectory, so a file one agent produced is never
   * delivered as another agent's work.
   */
  readonly outboxDir: string;
  /**
   * Senders allowed to drive Nova, as WeChat user ids.
   *
   * Empty means every sender may. The id is the SDK's `conversationId`, which is
   * the sender's `ilink_user_id` -- the first thing the bridge logs per turn, so
   * it is discoverable without guessing.
   */
  readonly allowedSenders: readonly string[];
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
  /**
   * Pin every conversation to this agent, refusing `/agent` switches.
   *
   * Unset means the user may switch between Nova's primary agents. Set it when a
   * bridge should present one fixed persona, so nobody can wander off it by
   * typing.
   */
  readonly onlyAgent: string | undefined;
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
  const statePath = readString(
    "NOVA_BRIDGE_STATE",
    join(homedir(), ".nova", "weixin-bridge", "sessions.json"),
  );
  const config: BridgeConfig = {
    novaBaseUrl,
    agentKey: readString("NOVA_AGENT_KEY", "main"),
    workspaceDir: readString("NOVA_WORKSPACE_DIR", process.cwd()),
    progressIntervalMs: readPositiveInt("NOVA_PROGRESS_INTERVAL_MS", 4000),
    maxTextChars: readPositiveInt("NOVA_MAX_TEXT_CHARS", 4000),
    currentAgentPath: readString(
      "NOVA_BRIDGE_CURRENT",
      statePath.replace(/sessions\.json$/, "current.json"),
    ),
    accountPath: readString(
      "NOVA_BRIDGE_ACCOUNT",
      statePath.replace(/sessions\.json$/, "account.json"),
    ),
    legacyAccountPath: statePath.replace(/sessions\.json$/, "agents.json"),
    statePath,
    spillDir: readString(
      "NOVA_BRIDGE_SPILL_DIR",
      join(homedir(), ".nova", "weixin-bridge", "out"),
    ),
    outboxDir: readString("NOVA_BRIDGE_OUTBOX", DEFAULT_OUTBOX_DIR),
    allowedSenders: readPathList("NOVA_ALLOWED_SENDERS"),
    sendRoots: readPathList("NOVA_SEND_ROOTS"),
    maxFileBytes: readPositiveInt("NOVA_MAX_FILE_MB", 100) * 1024 * 1024,
    keepAwake: readFlag("NOVA_KEEP_AWAKE"),
    stillWorkingMs: readPositiveInt("NOVA_STILL_WORKING_MS", 8000),
    onlyAgent: process.env.NOVA_AGENT_KEY?.trim() || undefined,
  };
  return authUser
    ? { ...config, authUser, authPassword }
    : config;
}
/**
 * One agent's outbox.
 *
 * Sessions are shared: one file keyed by `<agentKey>/<conversationId>` already
 * partitions them, and a file per agent held a single entry apiece.
 *
 * The outbox cannot be shared, because a file an agent produced must never be
 * delivered as another's work. Every bot reports the same `conversationId` for
 * the same WeChat user, so the directory is what keeps the two apart.
 */
export function configForAgent(
  base: BridgeConfig,
  agentKey: string,
): BridgeConfig {
  if (agentKey === base.agentKey) {
    return base;
  }
  const scoped = agentKey.replace(/[^A-Za-z0-9._-]/g, "_");
  return {
    ...base,
    agentKey,
    outboxDir: `${base.outboxDir.replace(/\/$/, "")}/${scoped}`,
  };
}
