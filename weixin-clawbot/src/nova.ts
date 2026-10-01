/**
 * Minimal Nova HTTP client: the chat SSE stream plus the two side-effect calls
 * a chat surface needs (approve, interrupt).
 *
 * The stream is an AI SDK v3 UI message stream. Nova's own extensions ride along
 * as `data-nova-*` parts, which is where session identity and approval requests
 * live -- the standard parts carry only assistant text and tool traffic.
 */

import * as log from "./log.js";
import type { BridgeConfig } from "./config.js";

/** One decoded SSE frame. `payload` is the whole JSON object on the wire. */
export interface NovaFrame {
  /** Frame type, e.g. `text-delta` or `data-nova-approval-required`. */
  readonly type: string;
  /** `id:` cursor assigned by Nova's stream buffer, absent on unbuffered frames. */
  readonly sequence: number | undefined;
  /** The raw decoded JSON object. */
  readonly payload: Record<string, unknown>;
}

/** An agent as `/api/agents` reports it. */
export interface NovaAgentSummary {
  readonly key: string;
  readonly name: string;
  readonly mode: string;
  readonly posture: string | null;
  readonly provider: string | null;
  readonly model: string | null;
}

/** Body for `POST /api/chat/stream`. */
export interface NovaChatRequest {
  /**
   * Which Nova agent runs this turn.
   *
   * Per request rather than per process: a chat surface switches agents with
   * `/agent`, and that must not need a restart.
   */
  readonly agentKey?: string | undefined;
  readonly sessionId?: string | undefined;
  readonly message: string;
  readonly attachments?: readonly NovaAttachment[];
  readonly resumeFromSeq?: number | undefined;
}

/**
 * An attachment in Nova's wire shape.
 *
 * `build_user_message` in `nova/agent/core.py` reads exactly two shapes and
 * silently drops everything else: `type: "image"` with a content part holding a
 * **data URL** in `image`, and `type: "document"` with a content part holding
 * already-extracted `text`. Nova never extracts document text itself, so the
 * bridge only ever builds image attachments.
 */
export interface NovaAttachment {
  readonly id: string;
  readonly type: "image";
  readonly name: string;
  readonly content_type: string;
  readonly content: readonly {
    readonly type: "image";
    readonly image: string;
  }[];
}

/** Raised when Nova answers a non-2xx status. */
export class NovaHttpError extends Error {
  constructor(
    readonly status: number,
    readonly body: string,
  ) {
    super(`Nova responded ${status}: ${body.slice(0, 300)}`);
    this.name = "NovaHttpError";
  }
}

/**
 * The `data` sub-object of a frame.
 *
 * Nova's `data-nova-*` parts nest their fields under `data`, while the standard
 * AI SDK parts carry them at the top level. Reading a `data-nova-*` field off the
 * top level silently yields "", so anything from that family must go through
 * here.
 */
export function frameData(frame: NovaFrame): Record<string, unknown> {
  const value = frame.payload["data"];
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return {};
  }
  return value as Record<string, unknown>;
}

/** Read a string field off a frame payload. */
export function frameString(frame: NovaFrame, key: string): string {
  const value = frame.payload[key];
  return typeof value === "string" ? value : "";
}

/** Read a string field off a frame's `data` sub-object. */
export function frameDataString(frame: NovaFrame, key: string): string {
  const value = frameData(frame)[key];
  return typeof value === "string" ? value : "";
}

/**
 * Keys that hold a filesystem path.
 *
 * Nova's tools spell this three different ways -- `read`/`edit`/`write` use
 * `filePath`, `read_image` uses `file_path`, `glob`/`grep` use `path` -- so any
 * single-key lookup silently misses two of them.
 */
const PATH_KEYS: readonly string[] = ["filePath", "file_path", "path"];

/**
 * The argument worth showing per tool, most specific first.
 *
 * A tool call in a chat bubble should say what it acted on, not dump its
 * arguments: `read` on a file needs the path, not `offset`/`limit`; `edit` needs
 * the path, not the before/after text. When several keys are listed they are
 * joined with " in ", which reads correctly for the pattern-plus-directory tools.
 */
const TOOL_ARGUMENTS: Readonly<Record<string, readonly string[]>> = {
  shell: ["command"],
  read: PATH_KEYS,
  read_image: PATH_KEYS,
  edit: PATH_KEYS,
  write: PATH_KEYS,
  glob: ["pattern", "path"],
  grep: ["pattern", "path"],
  web_search: ["query"],
  web_fetch: ["url"],
  delegate_to_agent: ["target"],
  subagent_status: ["target"],
  code_run: ["script_path", "cwd"],
  browser_use: ["action"],
  background_task_cancel: ["task_id"],
  background_task_logs: ["task_id"],
  background_task_status: ["task_id"],
  // save_memory is listed so its `content` never reaches a bubble through the
  // fallback; only the key identifies the memory.
  save_memory: ["key"],
  search_memory: ["query"],
  delete_memory: ["key"],
  list_memories: ["scope"],
  load_skill: ["skill_name"],
  install_skill: ["skill_ref"],
};

/**
 * Argument names that conventionally identify what an unknown tool acted on.
 *
 * MCP servers bring arbitrary schemas, so the per-tool table cannot cover them.
 * These are the names that carry the intent across tool ecosystems; the first
 * match wins, so the order runs from most to least specific.
 */
const CONVENTIONAL_ARGUMENTS: readonly string[] = [
  // what it runs
  "command", "cmd", "script", "code", "expression",
  // what it acts on
  "path", "filePath", "file_path", "file", "filename", "fileName",
  "dir", "directory", "url", "uri",
  // what it looks for
  "query", "q", "pattern", "glob", "prompt", "question", "search",
  // the content itself
  "text", "input", "content", "message", "body",
  // identity
  "target", "name", "id", "key", "skill_name", "skill_ref", "task_id",
];

/** Longest a tool summary may be before it is trimmed. */
const TOOL_SUMMARY_LIMIT = 120;

/** Collapse whitespace and clip, so a summary stays one readable line. */
function clip(value: string, limit: number): string {
  const flat = value.replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
}

/** Return a non-empty string argument, or undefined for anything else. */
function scalar(value: unknown): string | undefined {
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return undefined;
}

/**
 * Summarise a tool with no entry in the table.
 *
 * A value is shown only when it can be identified unambiguously: a conventional
 * argument name, or the tool's single string argument, which is the shape most
 * MCP tools take. Two unrecognised strings means the key order would be the only
 * thing deciding what the user sees, so nothing is shown instead -- a bubble
 * reading `→ some_tool` beats one asserting a guess. Numeric arguments are
 * excluded because a leading `timeout=300` buries the value that matters.
 */
function describeUnlistedTool(
  record: Record<string, unknown>,
  limit: number,
): string {
  for (const key of CONVENTIONAL_ARGUMENTS) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return clip(value, limit);
    }
  }
  const strings = Object.values(record).filter(
    (value): value is string => typeof value === "string" && value.trim() !== "",
  );
  return strings.length === 1 ? clip(strings[0]!, limit) : "";
}

/**
 * Drop a `1.` / `1、` / `1)` prefix the model wrote into the question text.
 *
 * Only a leading run of digits followed by one separator character, so a genuine
 * question that starts with a number ("2026 年的预算？") is left alone.
 */
function stripLeadingNumber(text: string): string {
  return text.replace(/^\d{1,2}[.、)）]\s*/, "");
}

/** One question as `ask_user` announced it. */
interface AskUserQuestion {
  readonly header: string;
  readonly question: string;
  readonly inputType: string;
  readonly options: readonly { readonly label: string; readonly description: string }[];
  readonly required: boolean;
  readonly default: string;
}

/**
 * Render the questions an `ask_user` call is asking.
 *
 * These arrive on the tool's `tool-input-available` frame, not on
 * `data-nova-input-required` -- that frame only says "User input required" and
 * carries no questions at all, so a bridge that reads it has nothing to show the
 * user. The turn is paused until the next message, which the SDK delivers as an
 * ordinary message on the same session, so the answer needs no special handling:
 * rendering the questions is the whole of the client side.
 *
 * Returns nothing when the payload is not the documented shape, so a provider
 * that sends something else degrades to the generic tool line rather than
 * printing `[object Object]`.
 */
export function describeAskUser(input: unknown): readonly string[] {
  if (typeof input !== "object" || input === null) {
    return [];
  }
  const raw = (input as Record<string, unknown>)["questions"];
  if (!Array.isArray(raw) || raw.length === 0) {
    return [];
  }

  const questions: AskUserQuestion[] = [];
  for (const entry of raw) {
    if (typeof entry !== "object" || entry === null) {
      continue;
    }
    const record = entry as Record<string, unknown>;
    const text = typeof record["question"] === "string" ? record["question"] : "";
    const header =
      typeof record["header"] === "string" ? record["header"].trim() : "";
    // Models often number the question inside `question` themselves, and the
    // bridge adds its own. Left alone the user reads "1. 【城市】1. 你在哪？",
    // and the reply they type then looks like it belongs to a different question.
    const body = stripLeadingNumber(text.trim()) || header;
    if (body === "") {
      continue;
    }
    const options = Array.isArray(record["options"])
      ? record["options"]
          .filter(
            (option): option is Record<string, unknown> =>
              typeof option === "object" && option !== null,
          )
          .map((option) => ({
            label:
              typeof option["label"] === "string" ? option["label"].trim() : "",
            description:
              typeof option["description"] === "string"
                ? option["description"].trim()
                : "",
          }))
          .filter((option) => option.label !== "")
      : [];
    questions.push({
      // A header is a short label, so it is only worth showing when it says
      // something the question does not.
      header: text.trim() ? header : "",
      question: body,
      inputType:
        typeof record["input_type"] === "string" ? record["input_type"] : "text",
      options,
      required: record["required"] !== false,
      default: typeof record["default"] === "string" ? record["default"] : "",
    });
  }
  if (questions.length === 0) {
    return [];
  }

  const lines: string[] = [];
  questions.forEach((question, index) => {
    const label = question.header !== "" ? `【${question.header}】` : "";
    const optional = question.required ? "" : "（可选）";
    lines.push(`${index + 1}. ${label}${question.question}${optional}`);
    if (question.inputType === "select") {
      // Deliberately unnumbered. A numbered option ("2.2", "b)") invites an
      // answer that quotes the number back, and the model then reads it as the
      // user pointing at a rendered line rather than choosing -- it reports "you
      // sent the template number, not an answer". Naming the choice is what
      // people do anyway, and it is what the model matches on.
      for (const option of question.options) {
        const detail =
          option.description !== "" ? ` —— ${option.description}` : "";
        lines.push(`   ${option.label}${detail}`);
      }
    } else if (question.default !== "") {
      lines.push(`   （默认：${question.default}）`);
    }
  });
  return lines;
}

/**
 * Summarise a tool call for one chat line: what the tool acted on.
 *
 * A listed tool contributes only its primary argument, or nothing: for a `read`
 * with no path in the payload, printing `offset=3` is noise, and silence reads
 * better than a wrong-looking detail. An unlisted tool -- an MCP server's, most
 * often -- falls back to conventional argument names.
 */
export function describeToolCall(
  toolName: string,
  input: unknown,
  limit = TOOL_SUMMARY_LIMIT,
): string {
  if (typeof input === "string") {
    return clip(input, limit);
  }
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    return "";
  }
  const record = input as Record<string, unknown>;

  const keys = TOOL_ARGUMENTS[toolName];
  if (keys === undefined) {
    return describeUnlistedTool(record, limit);
  }
  const parts = keys
    .map((key) => scalar(record[key]))
    .filter((part): part is string => part !== undefined);
  if (parts.length === 1) {
    return clip(parts[0]!, limit);
  }
  return parts.length > 1 ? clip(parts.join(" in "), limit) : "";
}

const SSE_BLOCK_SEPARATOR = "\n\n";

/**
 * Decode an SSE body into frames.
 *
 * Three line shapes matter here: `:ping` comments (heartbeats, ignored),
 * `id: <n>` sequence prefixes, and `data:` payloads. `data: [DONE]` closes the
 * stream and ends the generator.
 */
export async function* decodeSse(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<NovaFrame> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf(SSE_BLOCK_SEPARATOR);
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + SSE_BLOCK_SEPARATOR.length);
        const block2 = parseSseBlock(block);
        if (block2 === DONE) {
          return;
        }
        if (block2) {
          yield block2;
        }
        boundary = buffer.indexOf(SSE_BLOCK_SEPARATOR);
      }
    }
    const tail = parseSseBlock(buffer);
    if (tail && tail !== DONE) {
      yield tail;
    }
  } finally {
    reader.releaseLock();
  }
}

/** Sentinel returned for the `data: [DONE]` terminator. */
const DONE: unique symbol = Symbol("sse-done");

/**
 * Parse one SSE block.
 *
 * Returns `DONE` at the `data: [DONE]` terminator, and null for comments and
 * malformed blocks, so a caller can tell "stream finished" from "no frame here".
 */
function parseSseBlock(block: string): NovaFrame | typeof DONE | null {
  let sequence: number | undefined;
  let data: string | undefined;

  for (const rawLine of block.split("\n")) {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (!line || line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("id:")) {
      const parsed = Number.parseInt(line.slice(3).trim(), 10);
      if (Number.isFinite(parsed)) {
        sequence = parsed;
      }
      continue;
    }
    if (line.startsWith("data:")) {
      data = line.slice(5).trim();
    }
  }

  if (data === undefined) {
    return null;
  }
  if (data === "[DONE]") {
    return DONE;
  }
  try {
    const parsed: unknown = JSON.parse(data);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return null;
    }
    const record = parsed as Record<string, unknown>;
    const type = record["type"];
    if (typeof type !== "string") {
      return null;
    }
    return { type, sequence, payload: record };
  } catch {
    return null;
  }
}

/**
 * The Nova operations the agent depends on.
 *
 * Declared as an interface so a test can drive the agent from a canned frame
 * sequence -- notably the approval round trip, which a real model will not
 * reproduce on demand.
 */
export interface NovaLike {
  streamChat(
    request: NovaChatRequest,
    signal?: AbortSignal,
  ): AsyncGenerator<NovaFrame>;
  approve(
    sessionId: string,
    requestId: string,
    approved: boolean,
    remember?: boolean,
  ): Promise<void>;
  interrupt(sessionId: string): Promise<boolean>;
  ping(): Promise<void>;
  listAgents(): Promise<readonly NovaAgentSummary[]>;
}

/** Client for the subset of Nova's HTTP surface a chat surface needs. */
export class NovaClient implements NovaLike {
  constructor(private readonly config: BridgeConfig) {}

  /** Build the standard headers, adding Basic auth when configured. */
  private headers(accept: string): Record<string, string> {
    const headers: Record<string, string> = {
      accept,
      "content-type": "application/json",
    };
    if (this.config.authUser !== undefined) {
      const encoded = Buffer.from(
        `${this.config.authUser}:${this.config.authPassword ?? ""}`,
        "utf-8",
      ).toString("base64");
      headers["authorization"] = `Basic ${encoded}`;
    }
    return headers;
  }

  /**
   * List the agents a chat surface may switch to.
   *
   * Only `mode: "primary"` is eligible. Nova applies an agent's `posture` only
   * when `is_sub_agent` is true, and the HTTP chat path is always primary -- so
   * offering a `read_only` sub-agent here would hand it the full toolset while
   * claiming it was restricted.
   */
  async listAgents(): Promise<readonly NovaAgentSummary[]> {
    const response = await fetch(`${this.config.novaBaseUrl}/api/agents`, {
      headers: this.headers("application/json"),
    });
    if (!response.ok) {
      throw new NovaHttpError(response.status, await response.text());
    }
    const parsed: unknown = await response.json();
    const items =
      typeof parsed === "object" && parsed !== null
        ? (parsed as Record<string, unknown>)["items"]
        : null;
    if (!Array.isArray(items)) {
      return [];
    }
    return items
      .filter(
        (item): item is Record<string, unknown> =>
          typeof item === "object" && item !== null,
      )
      .filter((item) => item["mode"] === "primary")
      .map((item) => ({
        key: typeof item["key"] === "string" ? item["key"] : "",
        name: typeof item["name"] === "string" ? item["name"] : "",
        mode: "primary",
        posture: typeof item["posture"] === "string" ? item["posture"] : null,
        provider:
          typeof item["provider"] === "string" ? item["provider"] : null,
        model: typeof item["model"] === "string" ? item["model"] : null,
      }))
      .filter((agent) => agent.key !== "");
  }

  /** Check that Nova is reachable and configured with at least one provider. */
  async ping(): Promise<void> {
    const response = await fetch(`${this.config.novaBaseUrl}/health`, {
      headers: this.headers("application/json"),
    });
    if (!response.ok) {
      throw new NovaHttpError(response.status, await response.text());
    }
  }

  /**
   * Stream one turn.
   *
   * Aborting `signal` closes the socket, which parks the turn as detached on
   * Nova's side rather than cancelling it -- use `interrupt()` to actually stop
   * the agent.
   */
  async *streamChat(
    request: NovaChatRequest,
    signal?: AbortSignal,
  ): AsyncGenerator<NovaFrame> {
    const body: Record<string, unknown> = {
      message: request.message,
      // Per request, so `/agent` can switch without a restart. Falling back to
      // the configured agent keeps the single-agent case working unchanged.
      agent_key: request.agentKey ?? this.config.agentKey,
      workspace_dir: this.config.workspaceDir,
    };
    if (request.sessionId !== undefined) {
      body["session_id"] = request.sessionId;
    }
    if (request.attachments !== undefined && request.attachments.length > 0) {
      body["attachments"] = request.attachments;
    }
    if (request.resumeFromSeq !== undefined) {
      body["resume_from_seq"] = request.resumeFromSeq;
    }

    const response = await fetch(`${this.config.novaBaseUrl}/api/chat/stream`, {
      method: "POST",
      headers: this.headers("text/event-stream"),
      body: JSON.stringify(body),
      ...(signal ? { signal } : {}),
    });
    if (!response.ok) {
      throw new NovaHttpError(response.status, await response.text());
    }
    if (response.body === null) {
      throw new Error("Nova returned an empty SSE body");
    }
    yield* decodeSse(response.body);
  }

  /**
   * Answer a pending approval.
   *
   * `sessionId` is passed as a query parameter so Nova can enforce that the
   * request belongs to the session resolving it.
   */
  async approve(
    sessionId: string,
    requestId: string,
    approved: boolean,
    remember = false,
  ): Promise<void> {
    const url = new URL(`${this.config.novaBaseUrl}/api/chat/approve`);
    url.searchParams.set("session_id", sessionId);
    const response = await fetch(url, {
      method: "POST",
      headers: this.headers("application/json"),
      body: JSON.stringify({
        request_id: requestId,
        approved,
        remember,
      }),
    });
    if (!response.ok) {
      throw new NovaHttpError(response.status, await response.text());
    }
  }

  /** Ask Nova to stop the agent running in `sessionId`. */
  async interrupt(sessionId: string): Promise<boolean> {
    const response = await fetch(`${this.config.novaBaseUrl}/api/chat/interrupt`, {
      method: "POST",
      headers: this.headers("application/json"),
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!response.ok) {
      throw new NovaHttpError(response.status, await response.text());
    }
    const parsed: unknown = await response.json();
    if (typeof parsed !== "object" || parsed === null) {
      return false;
    }
    return (parsed as Record<string, unknown>)["interrupted"] === true;
  }
}

/** Attachment media types Nova's `build_user_message` can actually ingest. */
const IMAGE_MIME_TYPES: ReadonlySet<string> = new Set([
  "image/png",
  "image/jpeg",
  "image/jpg",
  "image/gif",
  "image/webp",
]);

/**
 * Build an image attachment from a WeChat media file, or return null when the
 * media type cannot be forwarded.
 *
 * Anything other than a recognised image is dropped rather than approximated.
 * Nova ignores unrecognised attachments outright, and quietly injecting a local
 * path into the prompt would hand any WeChat sender a filesystem probe.
 */
export async function imageAttachmentFromFile(
  filePath: string,
  mimeType: string,
): Promise<NovaAttachment | null> {
  const normalized = mimeType.split(";")[0]?.trim().toLowerCase() ?? "";
  if (!IMAGE_MIME_TYPES.has(normalized)) {
    return null;
  }
  const { readFile } = await import("node:fs/promises");
  const bytes = await readFile(filePath);
  log.debug("image attachment loaded", filePath, `${bytes.length}B`);
  return {
    id: `att_${Date.now().toString(36)}`,
    type: "image",
    name: filePath.split("/").pop() ?? "image",
    content_type: normalized,
    content: [
      { type: "image", image: `data:${normalized};base64,${bytes.toString("base64")}` },
    ],
  };
}