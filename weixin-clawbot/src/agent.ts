/**
 * The `Agent` implementation: WeChat messages in, Nova turns out.
 *
 * Two shapes of interaction meet here. Ordinary messages start a background
 * turn whose answer is pushed as it progresses, because a turn can outlast the
 * SDK's per-message dispatch and WeChat has no streaming. Slash commands are
 * answered inline so they can never be shadowed by a running turn.
 */

import type { Agent, Bot, ChatRequest, ChatResponse } from "weixin-agent-sdk";
import { ApprovalRegistry, parseApprovalReply } from "./approvals.js";
import type { KeepAwake } from "./awake.js";
import { configForAgent, type BridgeConfig } from "./config.js";
import * as log from "./log.js";
import {
    frameData,
    frameDataString,
    frameString,
    imageAttachmentFromFile,
    describeToolCall,
    type NovaAgentSummary,
    describeAskUser,
    type NovaAttachment,
    type NovaLike,
} from "./nova.js";
import {
    consumeOutboxFile,
    ensureOutbox,
    explainRefusal,
    listOutbox,
    resolveSendable
} from "./outbox.js";
import { ProgressReporter, type SendFn } from "./reporter.js";
import { turnKey, TurnGate } from "./turn-gate.js";
import type { CurrentAgentStore } from "./current-agent.js";
import type { SessionStore } from "./sessions.js";

/** Commands handled without touching Nova. */
const COMMANDS: Readonly<Record<string, string>> = {
    "/help": [
        "Nova 微信桥接",
        "",
        "/status 当前会话状态",
        "/agent 列出可切换的 agent",
        "/agent <序号> 切换到第 N 个",
        "/stop 中断正在运行的任务",
        "/send <绝对路径> 发送文件到微信",
        "/clear 清除会话映射（SDK 内置）",
        "",
        "直接发消息即可开始一个任务；执行危险命令时会在这里追问确认。",
    ].join("\n"),
    "/send": [
        "把文件发到微信。",
        "",
        "/send /绝对/路径/report.pdf",
        "",
        "只允许工作区和收件箱目录内的文件。",
        "让 Nova 交付文件的方式：把文件放进收件箱，回合结束会自动发送。",
    ].join("\n"),
};

/** Upper bound on how far apart still-working notices can drift. */
const STILL_WORKING_MAX_GAP_MS = 120_000;

/** Reply for a sender outside `NOVA_ALLOWED_SENDERS`. */
const SENDER_REJECTED =
    "这个助手是私人的，暂不接受陌生人的请求。";

/** Human-readable file size for a chat bubble. */
function formatBytes(bytes: number): string {
    if (bytes < 1024) {
        return `${bytes}B`;
    }
    if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(1)}KB`;
    }
    return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

/** Per-conversation runtime state. */
interface TurnState {
    /** Aborts the in-flight stream; `/stop` triggers it. */
    readonly controller: AbortController;
    /** Gate key: namespaced, so two agents never collide on one conversation. */
    readonly key: string;
    /**
     * The agent this turn runs under, captured at admission.
     *
     * `/agent` is refused while a turn holds the gate, so this cannot change
     * underneath the run -- but capturing it means the store, the outbox and the
     * request all agree even if that guard is ever relaxed.
     */
    readonly agentKey: string;
    /** Session the turn is bound to, once known. */
    sessionId: string | undefined;
    /** Set when Nova reports the turn was interrupted or dropped. */
    cancelled: boolean;
    /** Whether anything at all has been pushed for this turn yet. */
    spoke: boolean;
    /**
     * Narration already pushed as progress for the current round.
     *
     * The model says what it is about to do before it does it, and that has to
     * reach the user ahead of the tool line -- otherwise the tool calls appear
     * unexplained. Kept rather than cleared, so a turn that narrates and then
     * ends still has something to close on; compared against the current answer
     * so the closing line does not repeat what was already shown.
     */
    narrated: string | null;
    /**
     * Whether the turn paused to ask the user something.
     *
     * `ask_user` ends the turn with no answer of its own, so without this the
     * closing line would claim the task finished having returned nothing, right
     * after asking a question that looks unanswered.
     */
    awaitingInput: boolean;
    /**
     * Outbox contents when the turn began.
     *
     * Only files that appear after this point belong to this turn. Without it an
     * interrupted turn leaves its files behind -- `/stop` returns before the
     * drain runs -- and the next sender would inherit them.
     */
    readonly outboxBaseline: ReadonlySet<string>;
    startedAt: number;
}

export class WeixinNovaAgent implements Agent {
    /**
     * Namespace for this agent's conversations.
     *
     * Every bot reports the same `conversationId` for the same WeChat user --
     * it is the sender's `ilink_user_id` -- so without a per-agent prefix two
     * bots would fight over one Nova session and blend two personas' history
     * into it.
     */
    private readonly namespace: string;
    private readonly gate: TurnGate;
    private readonly approvals = new ApprovalRegistry();
    /** This agent's running turns, so `/stop` and `/status` can find them. */
    private readonly turns = new Map<string, TurnState>();
    private keepAwake: KeepAwake | null = null;
    /** Which agent each conversation selected with `/agent`. */
    private readonly currentAgents: CurrentAgentStore | null;

    /**
     * Which agent a conversation is talking to.
     *
     * WeChat allows one ClawBot per account, so this is chosen in-band with
     * `/agent` rather than by which bot received the message.
     */
    private currentAgent(conversationId: string): string {
        if (this.config.onlyAgent !== undefined) {
            return this.config.onlyAgent;
        }
        return this.currentAgents?.get(conversationId) ?? this.namespace;
    }

    /** Namespace a conversation under an agent, isolating its state. */
    private key(agentKey: string, conversationId: string): string {
        return turnKey(agentKey, conversationId);
    }

    /** The outbox for an agent, so two agents cannot pick up each other's files. */
    private outboxFor(agentKey: string): string {
        return configForAgent(this.config, agentKey).outboxDir;
    }

    constructor(
        private readonly config: BridgeConfig,
        private readonly nova: NovaLike,
        private readonly sessions: SessionStore,
        private bot: Bot | null = null,
        gate?: TurnGate,
        options: { readonly currentAgents?: CurrentAgentStore } = {},
    ) {
        this.namespace = config.agentKey;
        this.gate = gate ?? new TurnGate();
        this.currentAgents = options.currentAgents ?? null;
    }

    /** Adopt the bot once `start()` has returned it, enabling proactive sends. */
    attachBot(bot: Bot): void {
        this.bot = bot;
    }

    /** Adopt the sleep assertion so `/status` can report whether it is held. */
    attachKeepAwake(keepAwake: KeepAwake): void {
        this.keepAwake = keepAwake;
    }

    /**
     * Resolve once no conversation has a turn in flight.
     *
     * Turns are detached by design, so callers that need to observe the end of one
     * (tests, shutdown) await this instead of racing a timer.
     */
    async whenIdle(): Promise<void> {
        while (this.gate.holder() !== null) {
            await new Promise((resolve) => {
                setTimeout(resolve, 50);
            });
        }
    }

    /**
     * Handle one inbound message.
     *
     * Returns immediately after admitting the work. Blocking here would stall the
     * SDK's serial dispatch loop and make `/stop` and approval answers
     * unreachable, so the turn runs detached and pushes its own output.
     */
    async chat(request: ChatRequest): Promise<ChatResponse> {
        const rawId = request.conversationId;
        const text = request.text.trim();

        if (text.startsWith("/")) {
            return await this.handleCommand(rawId, text);
        }

        const agentKey = this.currentAgent(rawId);
        const conversationId = this.key(agentKey, rawId);

        // The allowlist is keyed on the raw id: that is the `ilink_user_id` the
        // operator reads off `/status`, not a namespaced internal key.
        if (!this.isAllowedSender(rawId)) {
            log.warn("sender rejected", rawId, `agent=${agentKey}`);
            return { text: SENDER_REJECTED };
        }

        if (this.approvals.has(conversationId)) {
            const answer = parseApprovalReply(text);
            if (answer !== null) {
                return await this.resolveApproval(conversationId, answer);
            }
        }

        const gate = this.gate.acquire(conversationId);
        if (!gate.acquired) {
            return {
                text: gate.mine
                    ? [
                        "还有一个任务在跑。",
                        "",
                        "· `/stop` 中断它",
                        "· 等它结束再发下一条",
                    ].join("\n")
                    : [
                        "现在有另一个任务在跑，本次请求没有执行。",
                        "",
                        "等它结束后再发一次。",
                    ].join("\n"),
            };
        }
        return await this.startTurn(
            rawId,
            agentKey,
            conversationId,
            gate.controller,
            request,
        );
    }

    /**
     * Whether `conversationId` may drive Nova.
     *
     * An empty allowlist admits everyone, which is the single-user default. Once
     * `NOVA_ALLOWED_SENDERS` is set, a stranger is refused with a fixed reply and
     * never reaches the agent: that is the difference between someone asking your
     * agent a question and someone running tools on your machine.
     */
    private isAllowedSender(conversationId: string): boolean {
        if (this.config.allowedSenders.length === 0) {
            return true;
        }
        return this.config.allowedSenders.includes(conversationId);
    }

    /** Clear the conversation's Nova binding, as requested by the SDK. */
    clearSession(rawId: string): void {
        const agentKey = this.currentAgent(rawId);
        const conversationId = this.key(agentKey, rawId);
        this.stopTurn(rawId);
        this.approvals.clear(conversationId);
        void this.sessions.forget(conversationId);
        log.info("session cleared", conversationId);
    }

    /** Send a message to the WeChat user if the bot is attached yet. */
    private async send(
        message: string | ChatResponse,
        turn?: TurnState,
    ): Promise<void> {
        const bot = this.bot;
        if (bot === null) {
            log.warn("dropping message: bot not attached");
            return;
        }
        if (turn !== undefined) {
            turn.spoke = true;
        }
        await bot.sendMessage(message);
    }

    /**
     * Nudge a silent turn, then increasingly rarely.
     *
     * The SDK sends nothing when `chat()` returns no text, so a turn that takes
     * a while would otherwise look dead. The first notice arrives quickly, later
     * ones back off, and each carries the elapsed time so it reads as
     * information rather than a repeated ping. Any real output cancels the rest.
     */
    private startStillWorkingNudges(state: TurnState): () => void {
        let timer: NodeJS.Timeout | null = null;
        let delay = this.config.stillWorkingMs;

        const schedule = (): void => {
            timer = setTimeout(() => {
                if (state.cancelled || state.spoke) {
                    return;
                }
                const seconds = Math.round((Date.now() - state.startedAt) / 1000);
                void this.send(`仍在处理，已 ${seconds} 秒（/stop 中断）`, state);
                delay = Math.max(delay * 2, STILL_WORKING_MAX_GAP_MS);
                schedule();
            }, delay);
            timer.unref();
        };
        schedule();

        return () => {
            if (timer !== null) {
                clearTimeout(timer);
                timer = null;
            }
        };
    }

    /** Dispatch a slash command, keeping it out of Nova's way. */
    private async handleCommand(
        conversationId: string,
        text: string,
    ): Promise<ChatResponse> {
        const [name] = text.split(/\s+/, 1) as [string];
        const command = name.toLowerCase();

        if (command === "/help") {
            return { text: COMMANDS["/help"] ?? "" };
        }
        if (command === "/stop") {
            return this.stopTurn(conversationId);
        }
        if (command === "/status") {
            return { text: await this.describeStatus(conversationId) };
        }
        if (command === "/agent") {
            return await this.agentCommand(conversationId, text);
        }
        if (command === "/send") {
            return await this.sendFileCommand(text);
        }
        // /echo, /toggle-debug and /clear are consumed by the SDK before here.
        return { text: `未知命令 ${command}，发送 /help 查看可用命令。` };
    }

    /**
     * `/agent [序号或名字]`: list the switchable agents, or switch to one.
     *
     * WeChat allows a single ClawBot per account, so the agent is chosen in-band
     * rather than by which bot received the message. Each agent keeps its own
     * session store and outbox, so switching is the same as opening a separate
     * conversation with that agent, and switching back resumes it.
     *
     * An index is accepted because the keys are long and typing one into a chat
     * bubble is unpleasant. It resolves against a key-sorted list rather than
     * Nova's response order, so renaming an agent cannot silently redirect an
     * index to a different agent.
     */
    private async agentCommand(
        rawId: string,
        text: string,
    ): Promise<ChatResponse> {
        if (this.config.onlyAgent !== undefined) {
            return {
                text: `这个桥接固定在 ${this.config.onlyAgent}，不切换 agent。`,
            };
        }
        const store = this.currentAgents;
        if (store === null) {
            return { text: "这个桥接没有配置 agent 切换。" };
        }

        const target = text.split(/\s+/).slice(1).join(" ").trim();
        let agents: readonly NovaAgentSummary[];
        try {
            agents = await this.nova.listAgents();
        } catch (error) {
            log.warn("agent list failed", String(error));
            return { text: `读不到 agent 列表：${String(error)}` };
        }
        if (agents.length === 0) {
            return { text: "Nova 没有可用的主类型 agent。" };
        }

        // Ordered by key, not by Nova's response order. Nova sorts by display
        // name, so renaming an agent would shift every index and silently send
        // the user to a different one; a key is unique and does not move.
        const ordered = [...agents].sort((a, b) => a.key.localeCompare(b.key));
        const current = this.currentAgent(rawId);

        if (target === "") {
            const lines = ordered.map((agent, index) => {
                const mark = agent.key === current ? "  <- 当前" : "";
                // An agent with no provider is misconfigured; listing it plainly
                // beats an empty pair of brackets.
                const detail =
                    agent.provider === null || agent.provider === ""
                        ? agent.name
                        : `${agent.name}（${agent.provider}）`;
                return `${index + 1}. ${agent.key}  ${detail}${mark}`;
            });
            return {
                text: [
                    "可切换的 agent：",
                    "",
                    ...lines,
                    "",
                    "切换：/agent <序号>",
                ].join("\n"),
            };
        }

        // A bare number is an index. Agent keys may contain digits but never
        // start with one in practice, and preferring the index keeps `/agent 1`
        // from being ambiguous with a hypothetical key called "1".
        const resolved = /^\d+$/.test(target)
            ? ordered[Number(target) - 1]
            : ordered.find((agent) => agent.key === target);
        if (resolved === undefined) {
            return {
                text: /^\d+$/.test(target)
                    ? `没有第 ${target} 个 agent，共 ${ordered.length} 个。发送 /agent 看名单。`
                    : `没有名为 ${target} 的主类型 agent。发送 /agent 看名单，或用序号切换。`,
            };
        }
        const targetKey = resolved.key;
        if (!/^[A-Za-z0-9._-]+$/.test(targetKey)) {
            return {
                text: `agent 名字 ${targetKey} 不合法，只能用字母、数字、. _ -`,
            };
        }
        if (targetKey === current) {
            return { text: `已经在跟 ${targetKey} 说话了。` };
        }

        // Checked before the gate: a turn waiting on an approval still holds the
        // gate, and "还有一个任务在跑" would send the user to `/stop`, throwing
        // away work that only needs a `y`.
        if (this.approvals.has(this.key(current, rawId))) {
            return { text: "有一个审批还没回复，先回复 y 或 n 再切换。" };
        }
        // Otherwise a live turn means switching now would move the user's pending
        // answer to an agent that has no idea what it is about.
        if (this.gate.holder() !== null) {
            return { text: "还有一个任务在跑，先 /stop 或等它结束再切换。" };
        }

        // Created here rather than at startup: an agent becomes reachable the
        // moment it is selected, and that is the first time anything can be
        // dropped into its outbox.
        await ensureOutbox(this.outboxFor(targetKey));
        await store.set(rawId, targetKey);
        log.info("agent switched", rawId, `${current} -> ${targetKey}`);
        return {
            // The key is echoed even when an index was typed, so a miscounted
            // index is visible before the next message goes to the wrong agent.
            text: `已切换到 ${targetKey}。${
                targetKey === this.namespace ? "" : "它有独立的会话记录。"
            }`,
        };
    }

    /** Roots a file may live under to be sendable. */
    private allowedRoots(): readonly string[] {
        return [
            this.config.workspaceDir,
            this.config.outboxDir,
            this.config.spillDir,
            ...this.config.sendRoots,
        ];
    }

    /** `/send <path>`: validate, upload, and report what happened. */
    private async sendFileCommand(text: string): Promise<ChatResponse> {
        const argument = text.split(/\s+/).slice(1).join(" ").trim();
        const resolution = await resolveSendable(
            argument,
            this.allowedRoots(),
            this.config.maxFileBytes,
        );
        if (!resolution.ok) {
            return {
                text: explainRefusal(resolution.reason, resolution.detail),
            };
        }
        return await this.deliverFile(
            resolution.path,
            resolution.name,
            resolution.bytes,
        );
    }

    /** Upload one file and describe the result. */
    private async deliverFile(
        path: string,
        name: string,
        bytes: number,
    ): Promise<ChatResponse> {
        try {
            await this.send({
                text: `${name}（${formatBytes(bytes)}）`,
                media: { type: "file", url: path, fileName: name },
            });
            return { text: `已发送 ${name}` };
        } catch (cause) {
            log.warn("file send failed", path, String(cause));
            return { text: `发送 ${name} 失败：${String(cause)}` };
        }
    }

    /**
     * Send anything the agent left in the outbox, then clear it.
     *
     * This is the reliable hand-off: the agent only has to put a file in one
     * directory, with no need to phrase a request the bridge has to parse out of
     * prose.
     */
    private async drainOutbox(state: TurnState): Promise<void> {
        const dir = this.outboxFor(state.agentKey);
        for (const path of await listOutbox(dir)) {
            if (state.outboxBaseline.has(path)) {
                // Produced before this turn started -- by an interrupted turn, most
                // likely. It belongs to whoever made it, not to this sender.
                log.warn("outbox file left from an earlier turn", path);
                continue;
            }
            const resolution = await resolveSendable(
                path,
                this.allowedRoots(),
                this.config.maxFileBytes,
            );
            if (!resolution.ok) {
                log.warn("outbox file skipped", path, resolution.reason);
                await this.send(
                    `收件箱文件未发送：${explainRefusal(resolution.reason, resolution.detail)}`,
                );
                continue;
            }
            log.info(
                "sending outbox file",
                resolution.path,
                formatBytes(resolution.bytes),
            );
            await this.deliverFile(
                resolution.path,
                resolution.name,
                resolution.bytes,
            );
            await consumeOutboxFile(dir, resolution.path);
        }
    }

    /** Cancel the running turn, if any, and report what happened. */
    private stopTurn(rawId: string): ChatResponse {
        const conversationId = this.key(this.currentAgent(rawId), rawId);
        this.approvals.clear(conversationId);
        const running = this.turns.get(conversationId);
        if (running === undefined) {
            return { text: "当前没有正在运行的任务。" };
        }
        running.cancelled = true;
        running.controller.abort();
        const sessionId = running.sessionId;
        if (sessionId !== undefined) {
            // Aborting the socket only parks the turn as detached; Nova has to be told
            // to stop the agent itself.
            void this.nova.interrupt(sessionId).catch((error: unknown) => {
                log.warn("interrupt failed", String(error));
            });
        }
        return { text: "已请求中断当前任务。" };
    }

    /** Render the current turn and binding state for `/status`. */
    private describeStatus(rawId: string): string {
        const agentKey = this.currentAgent(rawId);
        const conversationId = this.key(agentKey, rawId);
        const running = this.turns.get(conversationId);
        const sessionId = this.sessions.sessionFor(conversationId);
        const holder = this.gate.holder();
        const lines = [
            `Agent ${agentKey}`,
            `发送者 ${rawId}`,
            `会话 ${sessionId ?? "未建立"}`,
            `工作区 ${this.config.workspaceDir}`,
        ];
        if (running !== undefined) {
            const seconds = Math.round((Date.now() - running.startedAt) / 1000);
            lines.push(
                `状态 运行中 ${seconds}s${running.cancelled ? "（中断中）" : ""}`,
            );
        } else if (holder !== null) {
            // The agents share one workspace, so another turn is this user's
            // business too: it is running their code on the same files.
            lines.push(`状态 被 ${holder} 占用`);
        } else {
            lines.push("状态 空闲");
        }
        if (this.approvals.has(conversationId)) {
            lines.push("审批 等待回复 y/n");
        }
        const awake = this.keepAwake?.describe();
        if (awake !== null && awake !== undefined) {
            lines.push(awake);
        }
        return lines.join("\n");
    }

    /** Answer a pending approval and release the blocked Nova turn. */
    private async resolveApproval(
        conversationId: string,
        answer: { approved: boolean; remember: boolean },
    ): Promise<ChatResponse> {
        const approval = this.approvals.take(conversationId);
        if (approval === undefined) {
            return { text: "这个审批已经结束了。" };
        }
        try {
            await this.nova.approve(
                approval.sessionId,
                approval.requestId,
                answer.approved,
                answer.remember,
            );
        } catch (error) {
            log.warn("approve failed", String(error));
            return { text: `审批提交失败：${String(error)}` };
        }
        const verdict = answer.approved
            ? answer.remember
                ? "已允许，本会话内不再询问。"
                : "已允许，继续执行。"
            : "已拒绝，跳过该命令。";
        return { text: verdict };
    }

    /**
     * Admit a turn and run it detached.
     *
     * The acknowledgement is returned to the SDK (which sends it as the reply to
     * this message) and progress plus the final answer are pushed afterwards.
     */
    private async startTurn(
        rawId: string,
        agentKey: string,
        conversationId: string,
        controller: AbortController,
        request: ChatRequest,
    ): Promise<ChatResponse> {
        const state: TurnState = {
            controller,
            key: conversationId,
            agentKey,
            sessionId: this.sessions.sessionFor(conversationId),
            cancelled: false,
            spoke: false,
            narrated: null,
            awaitingInput: false,
            outboxBaseline: new Set(await listOutbox(this.outboxFor(agentKey))),
            startedAt: Date.now(),
        };
        this.turns.set(conversationId, state);
        log.info(
            `turn started agent=${agentKey} sender=${rawId} ` +
                `session=${state.sessionId ?? "new"} workspace=${this.config.workspaceDir}`,
        );

        const attachments = await this.collectAttachments(request);
        const droppedMedia =
            request.media !== undefined && attachments.length === 0
                ? request.media
                : null;

        void this.runTurn(
            conversationId,
            request.text,
            attachments,
            droppedMedia,
            state,
        );

        // No acknowledgement. The SDK skips a reply with no text, and an
        // unconditional "已收到" on every message is pure noise once the user has
        // seen it once. A slow turn is covered by the still-working notice
        // instead, which only fires when nothing else has been said.
        return {};
    }

    /** Convert inbound WeChat media into Nova attachments, dropping the rest. */
    private async collectAttachments(
        request: ChatRequest,
    ): Promise<readonly NovaAttachment[]> {
        const media = request.media;
        if (media === undefined) {
            return [];
        }
        try {
            const attachment = await imageAttachmentFromFile(
                media.filePath,
                media.mimeType,
            );
            return attachment === null ? [] : [attachment];
        } catch (error) {
            log.warn("attachment read failed", String(error));
            return [];
        }
    }

    /** Consume one Nova turn, pushing progress and the answer as they arrive. */
    private async runTurn(
        conversationId: string,
        message: string,
        attachments: readonly NovaAttachment[],
        droppedMedia: { type: string } | null,
        state: TurnState,
    ): Promise<void> {
        const stopNudges = this.startStillWorkingNudges(state);
        const send: SendFn = async (payload) => {
            await this.send(payload, state);
        };
        const reporter = new ProgressReporter(send, {
            intervalMs: this.config.progressIntervalMs,
            maxTextChars: this.config.maxTextChars,
            spillDir: this.config.spillDir,
            label: conversationId,
        });

        // Worth saying immediately: the attachment was dropped, and the user
        // should not wonder why their file was ignored.
        if (droppedMedia !== null) {
            await this.send(
                `（${droppedMedia.type} 类型 Nova 暂不支持，已忽略附件）`,
                state,
            );
        }

        let answer = "";
        let failure: string | null = null;

        try {
            for await (const frame of this.nova.streamChat(
                {
                    message,
                    agentKey: state.agentKey,
                    ...(state.sessionId !== undefined
                        ? { sessionId: state.sessionId }
                        : {}),
                    ...(attachments.length > 0 ? { attachments } : {}),
                },
                state.controller.signal,
            )) {
                switch (frame.type) {
                    case "data-nova-session": {
                        const sessionId = frameDataString(frame, "sessionId");
                        if (sessionId && sessionId !== state.sessionId) {
                            state.sessionId = sessionId;
                            await this.sessions.bind(conversationId, sessionId);
                            reporter.note(`会话 ${sessionId.slice(0, 8)}`);
                        }
                        break;
                    }
                    case "text-delta":
                        answer += frameString(frame, "delta");
                        break;
                    case "start-step":
                        // A new LLM round begins. Nova emits text before a tool
                        // call often enough that concatenating every delta
                        // splices the intermediate remarks into the answer, so
                        // each round starts the answer afresh and only the last
                        // one survives. DONE's own content is not an option: the
                        // SSE adapter sends it only when nothing was streamed.
                        answer = "";
                        state.narrated = null;
                        break;
                    case "tool-input-available": {
                        const tool = frameString(frame, "toolName");
                        const input = (frame.payload["input"] as unknown) ?? "";

                        // Whatever the model said before calling the tool is the
                        // user being told what is about to happen, so it goes out
                        // ahead of the tool line rather than being dropped when
                        // the next step resets the answer.
                        const narration = answer.trim();
                        if (narration !== "" && narration !== state.narrated) {
                            reporter.note(narration);
                            state.narrated = narration;
                        }

                        // The questions are the point of the call, so they go out
                        // as their own bubble immediately rather than waiting on
                        // the progress interval: the turn is about to stop and
                        // this is the one thing the user has to act on.
                        const questions =
                            tool === "ask_user" ? describeAskUser(input) : [];
                        // Counting the numbered lines rather than the questions:
                        // the renderer interleaves option lines under each one, so
                        // the bubbles are not a question count.
                        const questionCount = questions.filter((line) =>
                            /^\d+\. /.test(line),
                        ).length;
                        if (questions.length > 0) {
                            state.awaitingInput = true;
                            await reporter.flush();
                            await this.send(
                                [
                                    "需要你回答：",
                                    "",
                                    ...questions,
                                    "",
                                    `共 ${questionCount} 题，按题号回复即可，选项直接写名字，比如「1 马鞍山」「2 减脂」。`,
                                ].join("\n"),
                                state,
                            );
                            break;
                        }
                        const summary = describeToolCall(tool, input);
                        reporter.note(
                            `→ ${tool}${summary ? ` ${summary}` : ""}`,
                        );
                        break;
                    }
                    case "data-nova-tool-error":
                        reporter.note(
                            `✗ ${frameDataString(frame, "toolName")}`,
                        );
                        break;
                    case "data-nova-approval-required": {
                        const data = frameData(frame);
                        const sessionId =
                            typeof data["sessionId"] === "string" &&
                            data["sessionId"]
                                ? data["sessionId"]
                                : (state.sessionId ?? "");
                        const requestId =
                            typeof data["requestId"] === "string"
                                ? data["requestId"]
                                : "";
                        const command =
                            typeof data["command"] === "string"
                                ? data["command"]
                                : "";
                        const description =
                            typeof data["description"] === "string"
                                ? data["description"]
                                : "";
                        if (requestId && sessionId) {
                            this.approvals.open(conversationId, {
                                requestId,
                                sessionId,
                                command,
                                description,
                            });
                            await reporter.flush();
                            // Marked as spoken: the prompt already says the turn
                            // is waiting, so a still-working notice on top of it
                            // would be noise.
                            await this.send(
                                ApprovalRegistry.describe({
                                    requestId,
                                    sessionId,
                                    command,
                                    description,
                                }),
                                state,
                            );
                        }
                        break;
                    }
                    case "data-nova-approval-resolved":
                        this.approvals.clear(conversationId);
                        break;
                    case "data-nova-input-required":
                        // Carries no questions -- only "User input required" --
                        // so it is a signal, not something to render.
                        state.awaitingInput = true;
                        break;
                    case "abort":
                        state.cancelled = true;
                        break;
                    case "error":
                        failure =
                            frameString(frame, "errorText") ||
                            "Nova 报告了一个错误";
                        break;
                    default:
                        break;
                }
            }
        } catch (error) {
            if (state.cancelled || state.controller.signal.aborted) {
                failure = null;
            } else {
                failure =
                    error instanceof Error ? error.message : String(error);
                log.error("turn failed", conversationId, failure);
            }
        } finally {
            stopNudges();
            await reporter.close();
            if (this.turns.get(state.key) === state) {
                this.turns.delete(state.key);
            }
            this.gate.release(state.key);
        }

        if (state.cancelled) {
            await this.send("已中断。", state);
            return;
        }
        if (failure !== null) {
            await this.send(`执行出错：${failure}`, state);
            // A failed turn may still have produced deliverables worth delivering.
            await this.drainOutbox(state);
            return;
        }
        const trimmed = answer.trim();
        if (trimmed !== "" && trimmed === state.narrated) {
            // Already shown ahead of the tool call and nothing followed it.
            // Reporting "没有返回内容" would be wrong here: the turn said what it
            // was doing and the stream ended on the tool result.
            return;
        }
        if (state.awaitingInput && !trimmed) {
            // Nothing to report: the turn stopped to wait for the user, and the
            // questions have already been sent.
            return;
        }
        if (!trimmed) {
            await this.send("任务结束，但没有返回内容。", state);
        } else {
            await reporter.reply(trimmed);
        }
        // Whatever the agent dropped in the outbox goes out after the answer, so a
        // delivered file is the last thing the user sees.
        await this.drainOutbox(state);
    }
}
