/**
 * Entry point: verify Nova is up, then serve one WeChat bot.
 *
 * WeChat allows a single ClawBot per account, so there is exactly one bot here.
 * Which Nova agent answers is chosen in-band with `/agent` and recorded per
 * conversation, and every agent gets its own session store and outbox underneath
 * this bridge's paths -- the same WeChat user reaches all of them under one
 * conversation id, so sharing either would blend two personas' history together.
 */

import { isLoggedIn, login, start, type Bot } from "weixin-agent-sdk";
import { WeixinNovaAgent } from "./agent.js";
import { readBoundAccount, writeBoundAccount } from "./accounts.js";
import { KeepAwake } from "./awake.js";
import { loadConfig, type BridgeConfig } from "./config.js";
import { CurrentAgentStore } from "./current-agent.js";
import { error, info, setLogLevel, warn } from "./log.js";
import { NovaClient } from "./nova.js";
import { ensureOutbox } from "./outbox.js";
import { reportSdkMessage } from "./sdk-log.js";
import { SessionStore } from "./sessions.js";
import { TurnGate } from "./turn-gate.js";

/**
 * Resolve the bot to serve, scanning once if nothing is bound.
 *
 * A binding file from the earlier per-agent layout is not migrated: it recorded
 * one bot per Nova agent, and WeChat keeps only the last of those, so which
 * entry is still live is not something to guess at.
 */
async function resolveAccount(config: BridgeConfig): Promise<string | null> {
  const bound = await readBoundAccount(
    config.accountPath,
    config.legacyAccountPath,
  );
  if (bound.kind === "bound") {
    return bound.accountId;
  }
  if (bound.kind === "legacy") {
    // Not fatal: the SDK index may still name a live bot, and refusing to start
    // would strand a working setup over a bookkeeping file.
    warn(
      `${config.legacyAccountPath} records one bot per agent, which WeChat does ` +
        "not allow -- a second scan replaces the first, so at most one of those " +
        "is live. Run `npm run login` to bind a single bot and be sure.",
    );
  }

  if (isLoggedIn()) {
    info(
      "no bot recorded; serving the account the SDK stored. " +
        "Run `npm run login` to bind one explicitly.",
    );
    return "";
  }

  info("no WeChat bot bound; scan the QR code to bind one");
  const accountId = await login({
    log: (message: string) => info("login", message),
  });
  await writeBoundAccount(config.accountPath, accountId);
  return accountId;
}

async function main(): Promise<void> {
  const config = loadConfig();
  setLogLevel(process.env.NOVA_BRIDGE_LOG_LEVEL ?? "info");

  const nova = new NovaClient(config);
  try {
    await nova.ping();
    info("nova reachable", config.novaBaseUrl);
  } catch (cause) {
    error(
      `nova unreachable at ${config.novaBaseUrl}: ${String(cause)}. ` +
        "Start it with `nova serve`, or set NOVA_BASE_URL.",
    );
    process.exitCode = 1;
    return;
  }

  const accountId = await resolveAccount(config);
  if (accountId === null) {
    process.exitCode = 1;
    return;
  }

  // Bound to this pid, so a crash or restart releases the assertion instead of
  // leaving the machine awake with nothing to show for it.
  const keepAwake = new KeepAwake();
  if (config.keepAwake) {
    keepAwake.enable();
  }

  const currentAgents = new CurrentAgentStore(config.currentAgentPath);
  await currentAgents.load();

  const sessions = new SessionStore(config.statePath);
  await sessions.load();
  // One store, one outbox root. The agent half of the session key and the
  // per-agent outbox subdirectory are what separate the agents; partitioning
  // the store itself as well only meant a file per agent holding one entry.
  await ensureOutbox(config.outboxDir);

  const agent = new WeixinNovaAgent(config, nova, sessions, null, new TurnGate(), {
    currentAgents,
  });
  agent.attachKeepAwake(keepAwake);

  const abortController = new AbortController();
  let bot: Bot;
  try {
    bot = start(agent, {
      ...(accountId ? { accountId } : {}),
      abortSignal: abortController.signal,
      log: (message: string) => reportSdkMessage(message),
    });
  } catch (cause) {
    error(`could not start the bot: ${String(cause)}`);
    keepAwake.disable();
    process.exitCode = 1;
    return;
  }
  agent.attachBot(bot);
  info(
    `serving default agent "${config.agentKey}"` +
      (accountId ? ` on bot ${accountId}` : " on the stored account") +
      ` sessions=${config.statePath} outbox=${config.outboxDir}` +
      (config.onlyAgent === undefined ? "" : ` (pinned to ${config.onlyAgent})`),
  );
  info(
    "bridge ready",
    config.workspaceDir === undefined
      ? "workspaces resolved per agent by Nova"
      : `workspace=${config.workspaceDir}`,
  );
  if (config.onlyAgent !== undefined) {
    info("NOVA_AGENT_KEY is pinned, so /agent switches are refused");
  }

  const shutdown = (signal: string): void => {
    info(`received ${signal}, stopping bridge`);
    keepAwake.disable();
    abortController.abort();
  };
  process.on("SIGINT", () => {
    shutdown("SIGINT");
  });
  process.on("SIGTERM", () => {
    shutdown("SIGTERM");
  });

  await bot.wait();
  keepAwake.disable();
  info("bridge stopped");
}

await main();
