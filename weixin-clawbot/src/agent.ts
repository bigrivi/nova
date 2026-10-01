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
import type { BridgeConfig } from "./config.js";
import * as log from "./log.js";
import {
    frameData,
    frameDataString,
    frameString,
    imageAttachmentFromFile,
    describeToolCall,
    type NovaAttachment,
    type NovaLike,
} from "./nova.js";
import {
    consumeOutboxFile,
    explainRefusal,
    listOutbox,
    resolveSendable
} from "./outbox.js";
import { ProgressReporter, type SendFn } from "./reporter.js";
import type { SessionStore } from "./sessions.js";

/** Commands handled without touching Nova. */
const COMMANDS: Readonly<Record<string, string>> = {
    "/help": [
        "Nova 微信桥接",
        "",
        "/status 当前会话状态",
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
    /** Session the turn is bound to, once known. */
    sessionId: string | undefined;
    /** Set when Nova reports the turn was interrupted or dropped. */
    cancelled: boolean;
    /** Whether anything at all has been pushed for this turn yet. */
    spoke: boolean;
    startedAt: number;
}

export class WeixinNovaAgent implements Agent {
    private readonly turns = new Map<string, TurnState>();
    private readonly approvals = new ApprovalRegistry();
    private keepAwake: KeepAwake | null = null;

    constructor(
        private readonly config: BridgeConfig,
        private readonly nova: NovaLike,
        private readonly sessions: SessionStore,
        private bot: Bot | null = null,
    ) {}

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
        while (this.turns.size > 0) {
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
        const conversationId = request.conversationId;
        const text = request.text.trim();

        if (text.startsWith("/")) {
            return await this.handleCommand(conversationId, text);
        }

        if (this.approvals.has(conversationId)) {
            const answer = parseApprovalReply(text);
            if (answer !== null) {
                return await this.resolveApproval(conversationId, answer);
            }
        }

        const running = this.turns.get(conversationId);
        if (running !== undefined) {
            return {
                text: [
                    "还有一个任务在跑。",
                    "",
                    "· `/stop` 中断它",
                    "· 等它结束再发下一条",
                ].join("\n"),
            };
        }

        return await this.startTurn(conversationId, request);
    }

    /** Clear the conversation's Nova binding, as requested by the SDK. */
    clearSession(conversationId: string): void {
        this.stopTurn(conversationId);
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
            return { text: this.describeStatus(conversationId) };
        }
        if (command === "/send") {
            return await this.sendFileCommand(text);
        }
        // /echo, /toggle-debug and /clear are consumed by the SDK before here.
        return { text: `未知命令 ${command}，发送 /help 查看可用命令。` };
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
    private async drainOutbox(): Promise<void> {
        const dir = this.config.outboxDir;
        for (const path of await listOutbox(dir)) {
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
    private stopTurn(conversationId: string): ChatResponse {
        const running = this.turns.get(conversationId);
        this.approvals.clear(conversationId);
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
    private describeStatus(conversationId: string): string {
        const running = this.turns.get(conversationId);
        const sessionId = this.sessions.sessionFor(conversationId);
        const lines = [
            `会话 ${sessionId ?? "未建立"}`,
            `工作区 ${this.config.workspaceDir}`,
            `Agent ${this.config.agentKey}`,
        ];
        if (running === undefined) {
            lines.push("状态 空闲");
        } else {
            const seconds = Math.round((Date.now() - running.startedAt) / 1000);
            lines.push(
                `状态 运行中 ${seconds}s${running.cancelled ? "（中断中）" : ""}`,
            );
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
        conversationId: string,
        request: ChatRequest,
    ): Promise<ChatResponse> {
        const state: TurnState = {
            controller: new AbortController(),
            sessionId: this.sessions.sessionFor(conversationId),
            cancelled: false,
            spoke: false,
            startedAt: Date.now(),
        };
        this.turns.set(conversationId, state);

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
                        break;
                    case "tool-input-available": {
                        const tool = frameString(frame, "toolName");
                        const summary = describeToolCall(
                            tool,
                            (frame.payload["input"] as unknown) ?? "",
                        );
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
                        reporter.note("等待你的输入");
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
            this.turns.delete(conversationId);
        }

        if (state.cancelled) {
            await this.send("已中断。", state);
            return;
        }
        if (failure !== null) {
            await this.send(`执行出错：${failure}`, state);
            // A failed turn may still have produced deliverables worth delivering.
            await this.drainOutbox();
            return;
        }
        const trimmed = answer.trim();
        if (!trimmed) {
            await this.send("任务结束，但没有返回内容。", state);
        } else {
            await reporter.reply(trimmed);
        }
        // Whatever the agent dropped in the outbox goes out after the answer, so a
        // delivered file is the last thing the user sees.
        await this.drainOutbox();
    }
}
