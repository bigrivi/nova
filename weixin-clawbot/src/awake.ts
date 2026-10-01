/**
 * Idle-sleep assertion tied to the bridge's lifetime.
 *
 * A chat agent has to stay reachable, and macOS will happily idle-sleep a laptop
 * one minute after it is unplugged. `caffeinate -i -w <pid>` registers an
 * `IdleSystemSleepPrevented` assertion scoped to this process: when the bridge
 * exits -- cleanly, by crash, or via a restart -- the watcher sees the pid go
 * away and releases the assertion itself. That self-cleanup is the reason to
 * spawn a watcher instead of wrapping the command in a shell.
 *
 * It does not cover lid-close sleep. Clamshell sleep is a hardware policy that
 * power assertions do not override; only Apple's documented conditions (AC plus
 * an external display and input devices) or a different machine handles that.
 */

import { spawn, type ChildProcess } from "node:child_process";
import * as log from "./log.js";

/** Binary that owns the assertion. Overridable so tests need no real process. */
const CAFFEINATE = "/usr/bin/caffeinate";

/** Lifecycle of the assertion, as reported by `/status`. */
export type AwakeState = "off" | "held" | "unavailable" | "unsupported";

/** Spawn function shape, injected by tests. */
export type SpawnFn = (
  command: string,
  args: readonly string[],
  options: { detached: boolean; stdio: "ignore" },
) => ChildProcess;

/**
 * The exact command used, exposed so its shape can be asserted without
 * spawning anything.
 *
 * `-w` and a trailing utility are mutually exclusive per `caffeinate(8)`, so
 * the watcher is spawned on its own and pointed at our pid.
 */
export function keepAwakeCommand(pid: number, binary = CAFFEINATE): string {
  return `${binary} -i -w ${pid}`;
}

/** Holds a power assertion for as long as this process lives. */
export class KeepAwake {
  private watcher: ChildProcess | null = null;
  private state: AwakeState = "off";
  private detail = "";

  constructor(
    private readonly pid: number = process.pid,
    private readonly platform: string = process.platform,
    private readonly spawnFn: SpawnFn = spawn as unknown as SpawnFn,
  ) {}

  /** Whether an assertion is currently held. */
  isActive(): boolean {
    return this.state === "held";
  }

  /**
   * Acquire the assertion.
   *
   * Failure is reported rather than thrown: not being able to prevent sleep is
   * a degraded mode, not a reason to refuse to serve messages.
   */
  enable(): void {
    if (this.state === "held") {
      return;
    }
    if (this.platform !== "darwin") {
      this.state = "unsupported";
      this.detail = `非 macOS（${this.platform}），无需保活`;
      log.info("keep-awake skipped:", this.detail);
      return;
    }

    let child: ChildProcess;
    try {
      child = this.spawnFn(CAFFEINATE, ["-i", "-w", String(this.pid)], {
        detached: true,
        stdio: "ignore",
      });
    } catch (cause) {
      this.state = "unavailable";
      this.detail = String(cause);
      log.warn("keep-awake could not start:", this.detail);
      return;
    }

    // A missing binary surfaces asynchronously, not from the spawn call.
    child.once("error", (cause: Error) => {
      this.state = "unavailable";
      this.detail = cause.message;
      log.warn("keep-awake watcher failed:", cause.message);
    });
    child.once("exit", (code, signal) => {
      this.watcher = null;
      if (this.state === "held") {
        this.state = "unavailable";
        this.detail = `caffeinate 提前退出 code=${code ?? "-"} signal=${signal ?? "-"}`;
        log.warn("keep-awake assertion lost:", this.detail);
      }
    });

    child.unref();
    this.watcher = child;
    this.state = "held";
    this.detail = "";
    log.info("keep-awake held:", keepAwakeCommand(this.pid), `pid=${this.pid}`);
  }

  /** Release the assertion early. The watcher would exit on its own anyway. */
  disable(): void {
    const child = this.watcher;
    this.watcher = null;
    if (this.state === "held") {
      this.state = "off";
    }
    if (child !== null) {
      child.kill();
    }
  }

  /** One line for `/status`, or null when there is nothing to report. */
  describe(): string | null {
    switch (this.state) {
      case "held":
        return `保活 已启用 (caffeinate -i -w ${this.pid})`;
      case "unavailable":
        return `保活 不可用：${this.detail}`;
      case "unsupported":
        return `保活 不适用：${this.detail}`;
      case "off":
        return null;
    }
  }
}