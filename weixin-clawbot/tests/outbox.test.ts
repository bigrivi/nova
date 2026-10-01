/**
 * Tests for outbound file validation and outbox draining.
 *
 * A chat surface is an exfiltration path: the model and the user are both
 * untrusted sources of paths, so `resolveSendable` is the gate that decides
 * whether a file may leave the machine. These tests pin that gate.
 */

import assert from "node:assert/strict";
import { mkdir, mkdtemp, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";
import { loadConfig } from "../src/config.js";
import {
  consumeOutboxFile,
  ensureOutbox,
  explainRefusal,
  listOutbox,
  resolveSendable,
} from "../src/outbox.js";

const MB = 1024 * 1024;

/** Create a scratch tree with an allowed root and a forbidden sibling. */
async function fixture(): Promise<{ allowed: string; forbidden: string }> {
  const base = await mkdtemp(join(tmpdir(), "nova-outbox-"));
  const allowed = join(base, "workspace");
  const forbidden = join(base, "secrets");
  await mkdir(allowed, { recursive: true });
  await mkdir(forbidden, { recursive: true });
  return { allowed, forbidden };
}

/** Write a file inside `dir` and return its path. */
async function makeFile(dir: string, name: string, body = "x"): Promise<string> {
  const path = join(dir, name);
  await writeFile(path, body, "utf8");
  return path;
}

describe("resolveSendable", () => {
  it("accepts a regular file inside an allowed root", async () => {
    const { allowed } = await fixture();
    const path = await makeFile(allowed, "report.pdf", "hello");
    const result = await resolveSendable(path, [allowed], 10 * MB);
    assert.equal(result.ok, true);
    if (result.ok) {
      assert.equal(result.name, "report.pdf");
      assert.equal(result.bytes, 5);
    }
  });

  it("refuses a file outside every allowed root", async () => {
    const { allowed, forbidden } = await fixture();
    const path = await makeFile(forbidden, "id_rsa", "SECRET");
    const result = await resolveSendable(path, [allowed], 10 * MB);
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.equal(result.reason, "outside-allowed-roots");
    }
  });

  it("refuses a symlink that escapes an allowed root", async () => {
    const { allowed, forbidden } = await fixture();
    const secret = await makeFile(forbidden, "id_rsa", "SECRET");
    const link = join(allowed, "innocent.txt");
    await symlink(secret, link);
    const result = await resolveSendable(link, [allowed], 10 * MB);
    assert.equal(result.ok, false, "a link out of the root must not be sendable");
    if (!result.ok) {
      assert.equal(result.reason, "outside-allowed-roots");
    }
  });

  it("refuses a directory", async () => {
    const { allowed } = await fixture();
    await mkdir(join(allowed, "subdir"), { recursive: true });
    const result = await resolveSendable(join(allowed, "subdir"), [allowed], 10 * MB);
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.equal(result.reason, "not-a-file");
    }
  });

  it("refuses a relative path rather than guessing a root", async () => {
    const result = await resolveSendable("report.pdf", ["/tmp"], 10 * MB);
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.equal(result.reason, "not-absolute");
    }
  });

  it("refuses an empty argument", async () => {
    const result = await resolveSendable("   ", ["/tmp"], 10 * MB);
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.equal(result.reason, "empty-path");
    }
  });

  it("refuses a missing file", async () => {
    const { allowed } = await fixture();
    const result = await resolveSendable(join(allowed, "nope.txt"), [allowed], 10 * MB);
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.equal(result.reason, "not-found");
    }
  });

  it("refuses a file over the size cap and says by how much", async () => {
    const { allowed } = await fixture();
    const path = await makeFile(allowed, "big.bin", "y".repeat(3 * MB));
    const result = await resolveSendable(path, [allowed], 1 * MB);
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.equal(result.reason, "too-large");
      assert.match(result.detail, /MB/);
    }
  });

  it("accepts when the root is a parent of a nested path", async () => {
    const { allowed } = await fixture();
    await mkdir(join(allowed, "a", "b"), { recursive: true });
    const path = await makeFile(join(allowed, "a", "b"), "deep.txt");
    assert.equal((await resolveSendable(path, [allowed], MB)).ok, true);
  });

  it("accepts a file under an extra send root", async () => {
    // NOVA_SEND_ROOTS exists so a user can opt a directory in for sending; the
    // workspace is the only root the agent can read and write on its own.
    const { allowed, forbidden } = await fixture();
    const path = await makeFile(forbidden, "photo.jpg", "JPEGDATA");
    assert.equal((await resolveSendable(path, [allowed], MB)).ok, false);
    assert.equal(
      (await resolveSendable(path, [allowed, forbidden], MB)).ok,
      true,
      "opting a root in must make it sendable",
    );
  });

  it("strips surrounding quotes from a pasted path", async () => {
    const { allowed } = await fixture();
    const path = await makeFile(allowed, "quoted.txt");
    assert.equal((await resolveSendable(`"${path}"`, [allowed], MB)).ok, true);
  });
});

describe("explainRefusal", () => {
  it("gives an actionable message for every reason", () => {
    assert.match(explainRefusal("empty-path", ""), /用法/);
    assert.match(explainRefusal("not-absolute", "x.txt"), /绝对路径/);
    assert.match(explainRefusal("outside-allowed-roots", "/etc/passwd"), /拒绝/);
    assert.match(explainRefusal("not-found", "/tmp/x"), /不存在/);
    assert.match(explainRefusal("not-a-file", "/tmp"), /普通文件/);
    assert.match(explainRefusal("too-large", "200MB"), /太大/);
  });
});

describe("loadConfig send roots", () => {
  it("is empty when NOVA_SEND_ROOTS is unset", () => {
    delete process.env.NOVA_SEND_ROOTS;
    assert.deepEqual(loadConfig().sendRoots, []);
  });

  it("accepts colon and comma separated paths", () => {
    process.env.NOVA_SEND_ROOTS = "/tmp/a:/tmp/b,/tmp/c";
    assert.deepEqual(loadConfig().sendRoots, ["/tmp/a", "/tmp/b", "/tmp/c"]);
  });

  it("expands a leading ~", () => {
    process.env.NOVA_SEND_ROOTS = "~/Desktop:~/Downloads";
    const { sendRoots } = loadConfig();
    assert.equal(sendRoots.length, 2);
    assert.match(String(sendRoots[0]), /\/Desktop$/);
    assert.match(String(sendRoots[1]), /\/Downloads$/);
    assert.ok(
      !String(sendRoots[0]).includes("~"),
      "the tilde must be expanded",
    );
  });

  it("drops blank entries and trailing whitespace", () => {
    process.env.NOVA_SEND_ROOTS = " /tmp/a :: , /tmp/b , ";
    assert.deepEqual(loadConfig().sendRoots, ["/tmp/a", "/tmp/b"]);
  });

  it("never leaks send roots into the agent workspace", () => {
    process.env.NOVA_SEND_ROOTS = "/tmp/sendable";
    const config = loadConfig();
    assert.equal(config.sendRoots[0], "/tmp/sendable");
    assert.notEqual(
      config.workspaceDir,
      "/tmp/sendable",
      "an opted-in send root must not become the agent's workspace",
    );
  });
});

describe("outbox", () => {
  it("creates the directory and lists what is in it", async () => {
    const base = await mkdtemp(join(tmpdir(), "nova-outbox-list-"));
    const dir = join(base, "nested", "outbox");
    await ensureOutbox(dir);
    await makeFile(dir, "b.txt");
    await makeFile(dir, "a.txt");
    await makeFile(dir, ".hidden");

    const files = await listOutbox(dir);
    assert.deepEqual(
      files.map((path) => path.split("/").pop()),
      ["a.txt", "b.txt"],
      "hidden files are skipped and order is stable",
    );
  });

  it("skips subdirectories, which are the per-agent outboxes", async () => {
    // The per-agent outboxes live inside the base one, so a directory here is
    // structure the bridge made. Listing it would make every turn try to send a
    // folder and tell the user the file was refused.
    const base = await mkdtemp(join(tmpdir(), "nova-outbox-subdir-"));
    await mkdir(join(base, "writing-coach"), { recursive: true });
    await makeFile(base, "report.pdf");

    const files = await listOutbox(base);

    assert.deepEqual(
      files.map((path) => path.split("/").pop()),
      ["report.pdf"],
    );
  });

  it("returns nothing when the directory does not exist", async () => {
    const base = await mkdtemp(join(tmpdir(), "nova-outbox-missing-"));
    assert.deepEqual(await listOutbox(join(base, "absent")), []);
  });

  it("removes a file once it has been sent", async () => {
    const base = await mkdtemp(join(tmpdir(), "nova-outbox-consume-"));
    const path = await makeFile(base, "done.txt");
    await consumeOutboxFile(base, path);
    assert.deepEqual(await listOutbox(base), []);
  });
});