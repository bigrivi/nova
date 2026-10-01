/**
 * The bridge records the one bot it serves, and never loses it.
 *
 * The SDK's `logout()` wipes every stored account and its index is rewritten on
 * every scan, so the bridge keeps its own file. It is also where a binding from
 * the earlier per-agent layout is recognised: WeChat allows one ClawBot per
 * account, so such a file cannot be honoured and must be reported rather than
 * half-migrated.
 */

import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";
import { readBoundAccount, writeBoundAccount } from "../src/accounts.js";

/** A private state dir so the test never touches the real account store. */
async function sandbox(): Promise<{ state: string; account: string }> {
  const base = await mkdtemp(join(tmpdir(), "nova-bind-"));
  const state = join(base, "openclaw");
  process.env.OPENCLAW_STATE_DIR = state;
  return { state, account: join(base, "account.json") };
}

/** Write an SDK-style account index. */
async function writeIndex(state: string, ids: readonly string[]): Promise<void> {
  const dir = join(state, "openclaw-weixin");
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "accounts.json"), JSON.stringify(ids), "utf8");
}

/** Read the SDK account index back. */
async function readIndex(state: string): Promise<string[]> {
  const raw = await readFile(
    join(state, "openclaw-weixin", "accounts.json"),
    "utf8",
  );
  const parsed: unknown = JSON.parse(raw);
  return Array.isArray(parsed)
    ? parsed.filter((id): id is string => typeof id === "string")
    : [];
}

describe("the bound bot", () => {
  it("records the scanned account", async () => {
    const { account } = await sandbox();
    await writeBoundAccount(account, "bot-aaa");

    assert.deepEqual(await readBoundAccount(account), {
      kind: "bound",
      accountId: "bot-aaa",
    });
  });

  it("starts unbound when the file does not exist", async () => {
    const { account } = await sandbox();
    assert.deepEqual(await readBoundAccount(account), { kind: "unbound" });
  });

  it("puts the bound account in the SDK index", async () => {
    const { state, account } = await sandbox();
    await writeIndex(state, ["stale-bot"]);
    await writeBoundAccount(account, "bot-aaa");

    assert.deepEqual(await readIndex(state), ["bot-aaa"]);
  });

  it("reports a per-agent binding file as legacy instead of guessing", async () => {
    // Two entries, only one of which WeChat still honours. Picking either would
    // be a coin flip, so the caller is told to rescan instead.
    const { account } = await sandbox();
    await writeFile(
      account,
      JSON.stringify({ version: 1, bindings: { main: "bot-aaa" } }),
      "utf8",
    );

    assert.deepEqual(await readBoundAccount(account), { kind: "legacy" });
  });

  it("recognises the old file even when the new one does not exist", async () => {
    // The upgrade path: the per-agent file is all that is on disk. Ignoring it
    // would fall through to the SDK index, which appears to work right up until
    // it picks a bot WeChat already replaced.
    const { account } = await sandbox();
    const legacy = `${account}.legacy`;
    await writeFile(
      legacy,
      JSON.stringify({ version: 1, bindings: { main: "bot-aaa" } }),
      "utf8",
    );

    assert.deepEqual(await readBoundAccount(account, legacy), { kind: "legacy" });
  });

  it("prefers a real binding over the old file", async () => {
    const { account } = await sandbox();
    const legacy = `${account}.legacy`;
    await writeFile(
      legacy,
      JSON.stringify({ version: 1, bindings: { main: "bot-old" } }),
      "utf8",
    );
    await writeBoundAccount(account, "bot-new");

    assert.deepEqual(await readBoundAccount(account, legacy), {
      kind: "bound",
      accountId: "bot-new",
    });
  });

  it("re-binding replaces the record, as a rescan does in WeChat", async () => {
    const { account } = await sandbox();
    await writeBoundAccount(account, "bot-aaa");
    await writeBoundAccount(account, "bot-bbb");

    assert.deepEqual(await readBoundAccount(account), {
      kind: "bound",
      accountId: "bot-bbb",
    });
  });

  it("ignores a corrupted file rather than throwing", async () => {
    const { account } = await sandbox();
    await writeFile(account, "{not json", "utf8");
    assert.deepEqual(await readBoundAccount(account), { kind: "unbound" });

    // And binding still works afterwards.
    await writeBoundAccount(account, "bot-aaa");
    assert.deepEqual(await readBoundAccount(account), {
      kind: "bound",
      accountId: "bot-aaa",
    });
  });

  it("treats an empty account id as unbound", async () => {
    const { account } = await sandbox();
    await writeFile(account, JSON.stringify({ version: 1, accountId: "  " }), "utf8");
    assert.deepEqual(await readBoundAccount(account), { kind: "unbound" });
  });

  it("survives an interrupted write, leaving the previous record intact", async () => {
    const { account } = await sandbox();
    await writeBoundAccount(account, "bot-aaa");
    // The temporary file is what a crash would leave behind.
    await writeFile(`${account}.tmp`, "{partial", "utf8");

    assert.deepEqual(await readBoundAccount(account), {
      kind: "bound",
      accountId: "bot-aaa",
    });
  });
});
