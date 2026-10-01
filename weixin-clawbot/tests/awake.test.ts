/**
 * Tests for the idle-sleep assertion.
 *
 * The assertion is what keeps a laptop reachable while unplugged, so the two
 * properties that matter are that it is scoped to this process (a crash must
 * release it) and that its failure is visible rather than silent.
 */

import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { describe, it } from "node:test";
import type { ChildProcess } from "node:child_process";
import { KeepAwake, keepAwakeCommand } from "../src/awake.js";
import { loadConfig } from "../src/config.js";

/** A ChildProcess stand-in that records spawn options and can be driven. */
class FakeChild extends EventEmitter {
  unrefCalled = false;
  killed = false;

  unref(): this {
    this.unrefCalled = true;
    return this;
  }

  kill(): boolean {
    this.killed = true;
    return true;
  }
}

/** Records what would have been spawned, without touching the system. */
function recorder(): {
  calls: { command: string; args: readonly string[] }[];
  children: FakeChild[];
  spawnFn: (
    command: string,
    args: readonly string[],
    options: { detached: boolean; stdio: "ignore" },
  ) => ChildProcess;
} {
  const calls: { command: string; args: readonly string[] }[] = [];
  const children: FakeChild[] = [];
  return {
    calls,
    children,
    spawnFn: (command, args, options) => {
      calls.push({ command, args });
      assert.equal(options.detached, true, "the watcher must outlive this scope");
      assert.equal(options.stdio, "ignore", "the watcher must not inherit stdio");
      const child = new FakeChild();
      children.push(child);
      return child as unknown as ChildProcess;
    },
  };
}

describe("keepAwakeCommand", () => {
  it("watches this pid with an idle-sleep assertion", () => {
    assert.equal(keepAwakeCommand(4321), "/usr/bin/caffeinate -i -w 4321");
  });

  it("passes no utility argument, because -w would then be ignored", () => {
    // caffeinate(8): "-w ... is ignored when used with utility option".
    const [binary, ...args] = keepAwakeCommand(4321).split(" ");
    assert.equal(binary, "/usr/bin/caffeinate");
    assert.deepEqual(args, ["-i", "-w", "4321"]);
  });
});

describe("KeepAwake", () => {
  it("acquires the assertion on macOS", () => {
    const { calls, children, spawnFn } = recorder();
    const awake = new KeepAwake(999, "darwin", spawnFn);
    awake.enable();

    assert.equal(awake.isActive(), true);
    assert.deepEqual(calls[0]?.args, ["-i", "-w", "999"]);
    assert.equal(children[0]?.unrefCalled, true, "must not hold the event loop open");
    assert.match(String(awake.describe()), /保活 已启用/);
  });

  it("is idempotent, so a repeated enable does not stack assertions", () => {
    const { calls, spawnFn } = recorder();
    const awake = new KeepAwake(1, "darwin", spawnFn);
    awake.enable();
    awake.enable();
    assert.equal(calls.length, 1);
  });

  it("does nothing on a platform without power assertions", () => {
    const { calls, spawnFn } = recorder();
    const awake = new KeepAwake(1, "linux", spawnFn);
    awake.enable();

    assert.equal(calls.length, 0, "nothing may be spawned off macOS");
    assert.equal(awake.isActive(), false);
    assert.match(String(awake.describe()), /不适用/);
  });

  it("reports a spawn failure instead of throwing", () => {
    const awake = new KeepAwake(1, "darwin", () => {
      throw new Error("ENOENT");
    });
    assert.doesNotThrow(() => awake.enable());
    assert.equal(awake.isActive(), false);
    assert.match(String(awake.describe()), /不可用/);
  });

  it("reports a watcher that dies, so /status never lies about being awake", () => {
    const { children, spawnFn } = recorder();
    const awake = new KeepAwake(1, "darwin", spawnFn);
    awake.enable();
    assert.equal(awake.isActive(), true);

    // The assertion holder exiting means the Mac can sleep again.
    children[0]?.emit("exit", 1, null);

    assert.equal(awake.isActive(), false);
    assert.match(String(awake.describe()), /不可用/);
    assert.match(String(awake.describe()), /提前退出/);
  });

  it("releases the assertion on disable", () => {
    const { children, spawnFn } = recorder();
    const awake = new KeepAwake(1, "darwin", spawnFn);
    awake.enable();
    awake.disable();

    assert.equal(children[0]?.killed, true);
    assert.equal(awake.isActive(), false);
    assert.equal(awake.describe(), null, "nothing to report once released");
  });

  it("stays quiet when never enabled", () => {
    const awake = new KeepAwake(1, "darwin", recorder().spawnFn);
    assert.equal(awake.isActive(), false);
    assert.equal(awake.describe(), null);
  });
});

describe("NOVA_KEEP_AWAKE", () => {
  it("is off unless explicitly enabled", () => {
    for (const value of [undefined, "", "0", "false", "no", "off"]) {
      if (value === undefined) {
        delete process.env.NOVA_KEEP_AWAKE;
      } else {
        process.env.NOVA_KEEP_AWAKE = value;
      }
      assert.equal(loadConfig().keepAwake, false, `value: ${String(value)}`);
    }
  });

  it("accepts the usual truthy spellings", () => {
    for (const value of ["1", "true", "YES", " on "]) {
      process.env.NOVA_KEEP_AWAKE = value;
      assert.equal(loadConfig().keepAwake, true, `value: ${value}`);
    }
    delete process.env.NOVA_KEEP_AWAKE;
  });
});