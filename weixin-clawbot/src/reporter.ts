/**
 * Progressive delivery of a Nova turn into discrete WeChat messages.
 *
 * WeChat has no streaming and no message editing, so a token stream cannot be
 * forwarded directly. This reporter collapses the stream into a small number of
 * bubbles: tool progress is batched behind a fixed interval, and the final
 * answer is sent once when the turn ends.
 */

import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { ChatResponse } from "weixin-agent-sdk";
import * as log from "./log.js";

/** Sends one message to the logged-in WeChat user. */
export type SendFn = (message: string | ChatResponse) => Promise<void>;

/** Tuning for one turn's worth of progressive delivery. */
export interface ReporterOptions {
  /** Minimum gap between progress bubbles. */
  readonly intervalMs: number;
  /** Longest reply body before the overflow spills into a file attachment. */
  readonly maxTextChars: number;
  /** Directory for spilled replies. */
  readonly spillDir: string;
  /** Prefix for spilled file names, used to keep them sortable. */
  readonly label: string;
}

/** Longest progress bubble before it is trimmed. */
const MAX_PROGRESS_LINE_CHARS = 200;

/**
 * Rate-limited progress buffer for a single turn.
 *
 * Progress notes queue up and flush on one interval, so a burst of twenty tool
 * calls costs one or two bubbles rather than twenty. Timers are unref'd: a
 * pending flush must not keep the process alive after the turn is over.
 */
export class ProgressReporter {
  private queued: string[] = [];
  private timer: NodeJS.Timeout | null = null;
  private closed = false;

  constructor(
    private readonly send: SendFn,
    private readonly options: ReporterOptions,
  ) {}

  /** Queue a progress note. Empty and duplicate-adjacent notes are dropped. */
  note(line: string): void {
    if (this.closed) {
      return;
    }
    const trimmed = line.replace(/\s+/g, " ").trim();
    if (!trimmed) {
      return;
    }
    if (this.queued.at(-1) === trimmed) {
      return;
    }
    this.queued.push(
      trimmed.length > MAX_PROGRESS_LINE_CHARS
        ? `${trimmed.slice(0, MAX_PROGRESS_LINE_CHARS - 1)}…`
        : trimmed,
    );
    this.schedule();
  }

  /** Arm the flush timer unless one is already pending. */
  private schedule(): void {
    if (this.timer !== null || this.closed) {
      return;
    }
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.flush();
    }, this.options.intervalMs);
    this.timer.unref();
  }

  /** Send everything queued as one bubble. Safe to call when idle. */
  async flush(): Promise<void> {
    if (this.queued.length === 0) {
      return;
    }
    const body = this.queued.join("\n");
    this.queued = [];
    try {
      await this.send(body);
    } catch (error) {
      log.warn("progress bubble send failed", String(error));
    }
  }

  /**
   * Send the turn's final answer.
   *
   * WeChat truncates very long bodies, so anything past `maxTextChars` is
   * written to a file and attached instead of being silently cut.
   */
  async reply(text: string): Promise<void> {
    if (text.length <= this.options.maxTextChars) {
      await this.send(text);
      return;
    }
    const filePath = await this.spill(text);
    const fileName = filePath.split("/").pop() ?? "reply.md";
    const head = text.slice(0, this.options.maxTextChars);
    await this.send({
      text: `${head}\n\n… 全文见附件 ${fileName}`,
      media: { type: "file", url: filePath, fileName },
    });
  }

  /** Write over-long reply text to disk and return the file path. */
  private async spill(text: string): Promise<string> {
    await mkdir(this.options.spillDir, { recursive: true });
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const filePath = join(this.options.spillDir, `${this.options.label}-${stamp}.md`);
    await writeFile(filePath, text, "utf8");
    log.info("reply spilled to file", filePath, `${text.length} chars`);
    return filePath;
  }

  /** Stop queueing and flush whatever is left. */
  async close(): Promise<void> {
    this.closed = true;
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    await this.flush();
  }
}