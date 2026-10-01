/**
 * The bridge must not point every agent at one workspace.
 *
 * Nova resolves a workspace per agent -- the agent's own `workspace_dir`, else
 * `<nova home>/agents/<key>` (`_agent_dir` in `nova/app/runtime.py`). The bridge
 * used to always send `workspace_dir`, defaulting to its own cwd, which overrode
 * that: every agent ran in one shared directory, and a workspace configured on
 * the agent in Nova was ignored.
 *
 * The allowlist is pinned alongside the request because it is a security
 * boundary that has to track whatever the request resolves to.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { agentWorkspaceDir, loadConfig } from "../src/config.js";
import { buildChatBody } from "../src/nova.js";

const HOME = "/tmp/nova-home";
const base = loadConfig();

describe("the chat request", () => {
  it("omits workspace_dir by default, so Nova resolves it per agent", () => {
    assert.equal(base.workspaceDir, undefined, "the fixture must not pin one");

    const body = buildChatBody(base, { message: "hi" });

    assert.ok(
      !("workspace_dir" in body),
      `workspace_dir must be absent: ${JSON.stringify(body)}`,
    );
  });

  it("sends it when the operator pinned one", () => {
    const body = buildChatBody(
      { ...base, workspaceDir: "/tmp/explicit" },
      { message: "hi" },
    );

    assert.equal(body["workspace_dir"], "/tmp/explicit");
  });

  it("still carries the per-request agent and session", () => {
    const body = buildChatBody(base, {
      message: "hi",
      agentKey: "writing-coach",
      sessionId: "sess-1",
    });

    assert.equal(body["agent_key"], "writing-coach");
    assert.equal(body["session_id"], "sess-1");
    assert.ok(!("workspace_dir" in body));
  });
});

describe("agentWorkspaceDir", () => {
  it("falls back to the agent's own directory, like Nova does", () => {
    assert.equal(agentWorkspaceDir(HOME, "main", null), "/tmp/nova-home/agents/main");
    assert.equal(
      agentWorkspaceDir(HOME, "writing-coach", null),
      "/tmp/nova-home/agents/writing-coach",
    );
  });

  it("gives two agents two directories", () => {
    // The whole point: one bridge, several agents, none of them sharing a
    // workspace with another.
    assert.notEqual(
      agentWorkspaceDir(HOME, "main", null),
      agentWorkspaceDir(HOME, "writing-coach", null),
    );
  });

  it("prefers the agent's configured workspace", () => {
    assert.equal(agentWorkspaceDir(HOME, "travel-planner", "/srv/travel"), "/srv/travel");
  });

  it("treats a blank configured value as unset", () => {
    // Every agent in a stock Nova carries a null workspace_dir; an empty string
    // says the same thing and must not collapse to the home directory itself.
    assert.equal(agentWorkspaceDir(HOME, "main", "   "), "/tmp/nova-home/agents/main");
    assert.equal(agentWorkspaceDir(HOME, "main", ""), "/tmp/nova-home/agents/main");
  });

  it("expands a leading tilde, which is how a configured path may be stored", () => {
    const expanded = agentWorkspaceDir(HOME, "x", "~/projects/y");

    assert.ok(!expanded.startsWith("~"), "a tilde must not survive");
    assert.match(expanded, /\/projects\/y$/);
  });

  it("reads NOVA_HOME rather than assuming ~/.nova", () => {
    assert.equal(
      agentWorkspaceDir("/custom/nova", "main", null),
      "/custom/nova/agents/main",
    );
  });
});
