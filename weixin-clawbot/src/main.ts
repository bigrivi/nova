/**
 * Entry point: verify Nova is up, log into WeChat, then run the message loop.
 */

import { isLoggedIn, login, start, type Bot } from "weixin-agent-sdk";
import { WeixinNovaAgent } from "./agent.js";
import { KeepAwake } from "./awake.js";
import { loadConfig } from "./config.js";
import { error, info, setLogLevel } from "./log.js";
import { NovaClient } from "./nova.js";
import { ensureOutbox } from "./outbox.js";
import { SessionStore } from "./sessions.js";

/**
 * Start the bridge.
 *
 * Nova's reachability is checked before the WeChat login so a misconfigured
 * `NOVA_BASE_URL` fails immediately rather than after a scan.
 */
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

    const sessions = new SessionStore(config.statePath);
    await sessions.load();
    await ensureOutbox(config.outboxDir);
    info(`outbox ready ${config.outboxDir}`);

    // Bound to this pid, so a crash or restart releases the assertion instead of
    // leaving the machine awake with nothing to show for it.
    const keepAwake = new KeepAwake();
    if (config.keepAwake) {
        keepAwake.enable();
    }

    // Login must come first: `start()` refuses to run without a stored token, so
    // scanning afterwards would throw instead of prompting.
    if (!isLoggedIn()) {
        info("no WeChat account stored; scan the QR code to continue");
        await login({ log: (message: string) => info("login", message) });
        info("login complete");
    }

    const agent = new WeixinNovaAgent(config, nova, sessions);
    const abortController = new AbortController();

    let bot: Bot;
    try {
        bot = start(agent, {
            abortSignal: abortController.signal,
            log: (message: string) => info("sdk", message),
        });
    } catch (cause) {
        error(`could not start the WeChat bot: ${String(cause)}`);
        process.exitCode = 1;
        return;
    }
    agent.attachBot(bot);
    agent.attachKeepAwake(keepAwake);

    info(
        `bridge ready workspace=${config.workspaceDir} agent=${config.agentKey}`,
    );

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
