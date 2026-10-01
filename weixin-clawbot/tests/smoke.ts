/**
 * Smoke test against a running `nova serve`.
 *
 * This is the one place the bridge talks to a real server, so it covers what
 * unit tests cannot: that the wire shapes the bridge parses match what Nova
 * emits, and that a full turn produces a final answer.
 *
 * Usage:
 *   nova serve                                   # in another shell
 *   NOVA_BASE_URL=http://127.0.0.1:8765 \
 *   NOVA_AGENT_KEY=weixin npm run smoke
 */

import assert from "node:assert/strict";
import { loadConfig, type BridgeConfig } from "../src/config.js";
import { error, info, setLogLevel } from "../src/log.js";
import {
  frameDataString,
  frameString,
  NovaClient,
  type NovaFrame,
} from "../src/nova.js";
import { ProgressReporter } from "../src/reporter.js";
import { ApprovalRegistry } from "../src/approvals.js";
import { SessionStore } from "../src/sessions.js";
import { WeixinNovaAgent } from "../src/agent.js";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

/** Counters collected from one streamed turn. */
interface TurnTrace {
  sessionId?: string;
  text: string;
  tools: string[];
  errors: string[];
  approvals: string[];
  aborted: boolean;
  sawFinish: boolean;
}

/** Drive one turn through the bridge's own client and report what came back. */
async function runTurn(
  nova: NovaClient,
  sessionId: string | undefined,
  message: string,
): Promise<TurnTrace> {
  const trace: TurnTrace = {
    text: "",
    tools: [],
    errors: [],
    approvals: [],
    aborted: false,
    sawFinish: false,
  };

  for await (const frame of nova.streamChat({
    message,
    ...(sessionId !== undefined ? { sessionId } : {}),
  })) {
    applyFrame(frame, trace);
  }
  return trace;
}

/** Fold one SSE frame into the trace. Mirrors the switch in `agent.ts`. */
function applyFrame(frame: NovaFrame, trace: TurnTrace): void {
  switch (frame.type) {
    case "data-nova-session": {
      const value = frameDataString(frame, "sessionId");
      if (value) {
        trace.sessionId = value;
      }
      break;
    }
    case "text-delta":
      trace.text += frameString(frame, "delta");
      break;
    case "tool-input-available":
      trace.tools.push(frameString(frame, "toolName"));
      break;
    case "data-nova-tool-error":
      trace.errors.push(frameDataString(frame, "toolName"));
      break;
    case "data-nova-approval-required":
      trace.approvals.push(frameDataString(frame, "requestId"));
      break;
    case "abort":
      trace.aborted = true;
      break;
    case "finish":
      trace.sawFinish = true;
      break;
    default:
      break;
  }
}

async function main(): Promise<void> {
  setLogLevel(process.env.NOVA_BRIDGE_LOG_LEVEL ?? "warn");
  const config = loadConfig();
  const nova = new NovaClient(config);

  await nova.ping();
  info("nova reachable", config.novaBaseUrl);

  const first = await runTurn(nova, undefined, "say hi");
  assert.ok(first.sessionId, "first turn must yield a session id");
  assert.ok(
    first.sawFinish,
    `turn must reach a finish frame (frames: ${JSON.stringify(first)})`,
  );
  info(
    `turn 1 ok session=${first.sessionId.slice(0, 8)} ` +
      `text=${first.text.length}chars tools=${first.tools.length}`,
  );

  const second = await runTurn(nova, first.sessionId, "say hi again");
  assert.equal(
    second.sessionId,
    first.sessionId,
    "a known session id must be reused",
  );
  info("turn 2 ok session reused");

  // The full agent path, with a stubbed Bot: proves the detached-turn wiring,
  // session binding, and progress delivery work end to end without a login.
  const dir = await mkdtemp(join(tmpdir(), "nova-smoke-"));
  const isolated: BridgeConfig = {
    ...config,
    statePath: join(dir, "sessions.json"),
    spillDir: join(dir, "out"),
  };
  const store = new SessionStore(isolated.statePath);
  await store.load();

  const bubbles: string[] = [];
  const agent = new WeixinNovaAgent(isolated, nova, store);
  agent.attachBot({
    sendMessage: async (message: string | { text?: string }) => {
      bubbles.push(typeof message === "string" ? message : (message.text ?? ""));
    },
    wait: async () => undefined,
  } as unknown as Parameters<typeof agent.attachBot>[0]);

  const ack = await agent.chat({ conversationId: "smoke-conv", text: "hello" });
  assert.equal(
    ack.text,
    undefined,
    "a turn must be admitted silently; the SDK sends nothing without text",
  );

  await agent.whenIdle();

  assert.ok(
    bubbles.length > 0,
    "the agent must push output for a detached turn",
  );
  const bound = store.sessionFor("smoke-conv");
  assert.ok(bound, "the agent must bind the conversation to a Nova session");
  assert.notEqual(
    bound,
    first.sessionId,
    "a fresh conversation must get its own session, not reuse an unrelated one",
  );

  // The binding must survive a restart, and the next turn must land in it.
  const reopened = new SessionStore(isolated.statePath);
  await reopened.load();
  assert.equal(reopened.sessionFor("smoke-conv"), bound, "binding must persist");

  const status = await agent.chat({ conversationId: "smoke-conv", text: "/status" });
  assert.match(status.text ?? "", /会话/);
  assert.ok(
    (status.text ?? "").includes(bound),
    "/status must report the bound session id",
  );
  info(`agent ok bubbles=${bubbles.length} bound=${bound.slice(0, 8)}`);
  info("commands ok");

  assert.equal(ApprovalRegistry.describe.length > 0, true);
  info("smoke passed");
}

try {
  await main();
} catch (cause) {
  error(`smoke failed: ${String(cause)}`);
  process.exitCode = 1;
}