/** Bottom input area: multi-line textarea, Enter to submit, Shift+Enter for newline, slash command suggestions, ESC to interrupt */
import {
    type BoxRenderable,
    decodePasteBytes,
    type KeyBinding,
    type KeyEvent,
    type PasteEvent,
    SyntaxStyle,
    type TextareaRenderable,
} from "@opentui/core";
import { useEffect, useRef, useState } from "react";
import {
    displayPath,
    resolvePastedFiles,
    toNovaAttachment,
    type PastedFile,
} from "../lib/attachments.ts";
import { truncateMiddle } from "../lib/display-width.ts";
import { activeMention, completeMentions } from "../lib/file-completion.ts";
import {
    buildMentionCandidates,
    mentionText,
    selectableSubagents,
    type MentionCandidate,
} from "../lib/mentions.ts";
import { listAgents } from "../api/nova-api.ts";
import type { NovaAgentRecord } from "../api/types.ts";
import {
    historyDown,
    historyUp,
    isNavigatingHistory,
    rememberInput,
    resetHistoryCursor,
} from "../lib/input-history.ts";
import { cycleMode } from "../stores/permission-store.ts";
import {
    COMMANDS,
    matchCommands,
    parseCommand,
    type CommandSpec,
} from "../commands.ts";
import { useApprovalStore } from "../stores/approval-store.ts";
import { useAskUserStore } from "../stores/ask-user-store.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { useScreenStore } from "../stores/screen-store.ts";
import { runChatStream, requestInterrupt } from "../stream/chat-stream.ts";
import { useTheme } from "../context/theme.tsx";
import { WORKSPACE_DIR } from "../workspace.ts";
import { useMenuStore } from "../stores/menu-store.ts";

/** Distinguishes composers, so one instance cannot clear another's menu. */
let composerInstances = 0;
import { MENU_CHROME, MENU_ROWS } from "./MenuOverlay.tsx";

const COMPOSER_KEY_BINDINGS: KeyBinding[] = [
    { name: "enter", action: "submit" },
    { name: "enter", shift: true, action: "newline" },
];

const TEXTAREA_MIN_HEIGHT = 1;
const TEXTAREA_MAX_HEIGHT = 12;

/** Width reserved for the file name inside an attachment chip. */
const CHIP_NAME_WIDTH = 28;

export type ComposerCommandHandler = (id: string, args: string) => void;

export function Composer({
    onCommand,
    variant = "bar",
    placeholder = "Message Nova…",
}: {
    onCommand: ComposerCommandHandler;
    /** "bar" sits at the bottom of the transcript; "card" floats on the launch
     *  screen, where `LaunchFrame` owns the border. */
    variant?: "bar" | "card";
    placeholder?: string;
}) {
    const theme = useTheme();
    const isStreaming = useChatStore((state) => state.isStreaming);
    const activeAgentKey = useChatStore((state) => state.agentKey);
    const askActive = useAskUserStore((state) => state.active) !== null;
    const approvalPending = useApprovalStore((state) => state.pending) !== null;
    const screenCurrent = useScreenStore((state) => state.current) !== null;
    // Keep these calls separate: `||` would skip the later store hooks when an
    // earlier modal is open, desyncing React's hook chain.
    const modalOpen = askActive || approvalPending || screenCurrent;
    const textareaRef = useRef<TextareaRenderable>(null);
    const boxRef = useRef<BoxRenderable>(null);
    const instanceId = useRef(0);
    if (instanceId.current === 0) {
        instanceId.current = ++composerInstances;
    }
    const [suggestions, setSuggestions] = useState<CommandSpec[]>([]);
    const [mentions, setMentions] = useState<MentionCandidate[]>([]);
    // Sub-agents are re-read when the active agent changes: the roster is that
    // agent's children, not the whole catalog.
    const [subagents, setSubagents] = useState<NovaAgentRecord[]>([]);
    // Which `@token` the current candidates belong to. The listing is async, so
    // a stale list must never be applied to a token the user has since edited.
    const [mentionQuery, setMentionQuery] = useState<string | null>(null);
    // The catalog can change while this component stays mounted (a sub-agent was
    // just created), so it is re-read when the menu opens rather than once.
    const mentionMenuOpen = useRef(false);
    const [selectedIndex, setSelectedIndex] = useState(0);
    const [textareaHeight, setTextareaHeight] = useState(TEXTAREA_MIN_HEIGHT);
    // Keyed by the extmark that draws the chip: opentui deletes a virtual
    // extmark as a whole, so the attachment disappears with its label.
    const [attachments, setAttachments] = useState<
        { extmarkId: number; file: PastedFile }[]
    >([]);
    const attachmentType = useRef<number | null>(null);
    const mentionType = useRef<number | null>(null);
    const mentionStyleId = useRef<number | null>(null);
    const [mentionStyle, setMentionStyle] = useState<SyntaxStyle | null>(null);
    const mentionSeq = useRef(0);
    const navigatingHistory = useRef(false);

    // One syntax style for accepted mentions: the textarea needs it at
    // construction, and the id is what an extmark paints with.
    useEffect(() => {
        try {
            const style = SyntaxStyle.create();
            mentionStyleId.current = style.registerStyle("nova.mention", {
                fg: theme.feedback.running,
            });
            setMentionStyle(style);
        } catch {
            // Without a renderer the style cannot be created; mentions still work.
        }
    }, [theme.feedback.running]);

    function applyAgentCatalog(agents: NovaAgentRecord[]): void {
        // The active agent decides whose children may be delegated to;
        // hardcoding "main" offered the wrong roster after a switch.
        setSubagents(selectableSubagents(agents, activeAgentKey));
    }

    function loadAgentCatalog(): void {
        void listAgents()
            .then(applyAgentCatalog)
            .catch(() => {
                // An empty catalog only costs the agent suggestions; the file
                // half of the menu still works.
            });
    }

    useEffect(() => {
        let cancelled = false;
        void listAgents()
            .then((agents) => {
                if (!cancelled) applyAgentCatalog(agents);
            })
            .catch(() => {
                // Same trade-off as loadAgentCatalog.
            });
        return () => {
            cancelled = true;
        };
    }, [activeAgentKey]);

    useEffect(() => {
        if (modalOpen) {
            textareaRef.current?.blur();
        } else {
            textareaRef.current?.focus();
        }
    }, [modalOpen]);

    const chipOf = (file: PastedFile): string =>
        `▧ ${truncateMiddle(file.kind === "image" ? file.name : displayPath(file.path), CHIP_NAME_WIDTH)} ×`;

    /** Register the chip style once, after the textarea exists. */
    function attachmentTypeId(): number | null {
        const input = textareaRef.current;
        if (!input) return null;
        if (attachmentType.current === null) {
            attachmentType.current = input.extmarks.registerType("attachment");
        }
        return attachmentType.current;
    }

    /** Insert a chip for *image* without putting its path in the prompt. */
    function insertAttachment(file: PastedFile): void {
        const input = textareaRef.current;
        const typeId = attachmentTypeId();
        if (!input || typeId === null) return;
        const label = chipOf(file);
        const start = input.cursorOffset;
        input.insertText(`${label} `);
        const extmarkId = input.extmarks.create({
            start,
            // Cover the trailing space too: one backspace removes the chip
            // instead of nibbling at the separator first.
            end: start + label.length + 1,
            virtual: true,
            typeId,
        });
        setAttachments((list) => [...list, { extmarkId, file }]);
    }

    /** Drop attachments whose chip is no longer in the textarea. */
    function syncAttachments(): void {
        const input = textareaRef.current;
        const typeId = attachmentType.current;
        if (!input || typeId === null) return;
        const live = new Set(
            input.extmarks.getAllForTypeId(typeId).map((mark) => mark.id),
        );
        setAttachments((list) => {
            const kept = list.filter((item) => live.has(item.extmarkId));
            return kept.length === list.length ? list : kept;
        });
    }

    /** Remove every chip (they travel as attachments instead). */
    function clearAttachments(): void {
        const input = textareaRef.current;
        const typeId = attachmentType.current;
        if (input && typeId !== null) {
            for (const mark of input.extmarks.getAllForTypeId(typeId)) {
                input.extmarks.delete(mark.id);
            }
        }
        setAttachments([]);
    }

    const handlePaste = (event: PasteEvent): void => {
        const text = decodePasteBytes(event.bytes);
        if (!text.trim()) return;
        // Read the disk asynchronously, so the default paste has to be cancelled
        // now: after an await it has already inserted the text.
        event.preventDefault();
        void resolvePastedFiles(text).then((files) => {
            const input = textareaRef.current;
            if (!input) return;
            // Not a set of existing paths: insert the text ourselves (prose, a
            // URL, a half-copied list), which is the old paste behaviour.
            if (!files) {
                input.insertText(text.replace(/\r\n?/g, "\n"));
                return;
            }
            for (const file of files) insertAttachment(file);
        });
    };

    function refreshSuggestions(value: string): void {
        if (value.trim().startsWith("/")) {
            const items = matchCommands(value);
            setSuggestions(items);
            setMentions([]);
            setSelectedIndex(0);
        } else {
            setSuggestions([]);
            void refreshMentions(value);
        }
        const ta = textareaRef.current;
        if (ta) {
            const lines = ta.lineCount ?? 1;
            setTextareaHeight((prev) => {
                const next = Math.min(
                    TEXTAREA_MAX_HEIGHT,
                    Math.max(TEXTAREA_MIN_HEIGHT, lines),
                );
                return next === prev ? prev : next;
            });
        }
    }

    /** List `@` candidates for the token at the end of *value*. */
    async function refreshMentions(value: string): Promise<void> {
        const token = activeMention(value);
        if (!token) {
            mentionMenuOpen.current = false;
            setMentions([]);
            setMentionQuery(null);
            return;
        }
        if (!mentionMenuOpen.current) {
            mentionMenuOpen.current = true;
            loadAgentCatalog();
        }
        // The listing is async, so a slower older request must not overwrite the
        // answer for what is now in the composer.
        const seq = ++mentionSeq.current;
        const paths = await completeMentions(token.query, WORKSPACE_DIR);
        if (seq !== mentionSeq.current) return;
        setMentions(buildMentionCandidates(subagents, paths, token.query));
        setMentionQuery(token.query);
        setSelectedIndex(0);
    }

    /** Replace the active `@` token with the chosen agent or path.
     *
     *  Returns false when the text no longer matches the menu it came from — the
     *  caller must then fall through instead of swallowing the keypress. */
    function acceptMention(item: MentionCandidate): boolean {
        const input = textareaRef.current;
        const value = input?.plainText ?? "";
        const token = activeMention(value);
        if (!input || !token || token.query !== mentionQuery) {
            setMentions([]);
            setMentionQuery(null);
            return false;
        }
        const text = mentionText(item);
        const next = `${value.slice(0, token.start)}${text}${value.slice(token.start + 1 + token.query.length)}`;
        input.setText(next);
        input.cursorOffset = next.length;
        // A directory is a half-typed path — the user keeps appending to it, so
        // only a finished reference becomes one delete-able unit.
        if (item.kind !== "dir") {
            markMention(token.start, text);
        }
        refreshSuggestions(next);
        return true;
    }

    /** Make an accepted mention one unit: coloured, and removed by one backspace.
     *
     *  Virtual, like the attachment chips, is what makes the deletion wrapper
     *  swallow the whole span instead of one character. Styling is best-effort —
     *  a reference that is not yellow is still usable, so a failure here must not
     *  throw away the completion. */
    function markMention(start: number, text: string): void {
        const input = textareaRef.current;
        if (!input) return;
        try {
            if (mentionType.current === null) {
                mentionType.current = input.extmarks.registerType("mention");
            }
            input.extmarks.create({
                start,
                // Includes the trailing space, so deleting the mention does not
                // leave a stray separator behind.
                end: start + text.length,
                virtual: true,
                typeId: mentionType.current,
                styleId: mentionStyleId.current ?? undefined,
            });
        } catch {
            // Styling is a nicety; the text already landed.
        }
    }

    function clearComposer(): void {
        textareaRef.current?.clear();
        setSuggestions([]);
        setMentions([]);
        setTextareaHeight(TEXTAREA_MIN_HEIGHT);
    }

    async function submitCurrent(): Promise<void> {
        const value = textareaRef.current?.plainText ?? "";
        // Commands first: if input starts with / and is a known command, execute it directly (without relying on the async suggestions state)
        if (value.trim().startsWith("/")) {
            const parsed = parseCommand(value);
            const known =
                parsed &&
                COMMANDS.some(
                    (cmd) =>
                        cmd.id === parsed!.id ||
                        cmd.aliases.includes(parsed!.id),
                );
            if (parsed && known) {
                clearComposer();
                onCommand(parsed.id, parsed.args);
                return;
            }
        }
        // The mention menu owns Enter while it is open. Without this the textarea
        // submits whatever is typed — a bare `@` — and the user gets an answer to
        // a question they were still composing.
        if (mentions.length > 0) {
            const item = mentions[selectedIndex] ?? mentions[0];
            if (item && acceptMention(item)) return;
        }
        if (suggestions.length > 0) {
            const item = suggestions[selectedIndex];
            if (item) {
                const parsed = parseCommand(item.usage);
                if (parsed) {
                    clearComposer();
                    onCommand(parsed.id, parsed.args);
                }
            }
            return;
        }
        if (!value.trim() || isStreaming) {
            return;
        }
        const body = attachments
            .reduce((text, item) => text.replace(`${chipOf(item.file)} `, ""), value)
            .trim();
        // Images travel as attachments; files are referenced by path so the
        // agent reads them with its own tools (permissions still apply).
        const images = attachments.flatMap((item) =>
            item.file.kind === "image" && item.file.image
                ? [toNovaAttachment(item.file.image)]
                : [],
        );
        const references = attachments.flatMap((item) =>
            item.file.kind === "file"
                ? [`Attached file: \`${displayPath(item.file.path)}\``]
                : [],
        );
        const message = [body, ...references].filter(Boolean).join("\n");
        if (!message || isStreaming) return;
        // Only the typed prompt goes into history; the decorated `message`
        // carries attachment lines the user never wrote.
        if (body) rememberInput(body);
        // A file-only message still needs something to show in the bubble.
        const display =
            body ||
            attachments
                .filter((item) => item.file.kind === "file")
                .map((item) => `▧ ${item.file.name}`)
                .join(" ");
        clearComposer();
        clearAttachments();
        await runChatStream({
            message,
            displayText: display || undefined,
            attachments: images,
        });
    }

    function handleKeyDown(event: KeyEvent): void {
        // Handled here as well as in App: whichever listener runs first, the
        // textarea must not insert a tab for Shift+Tab.
        if (event.shift && event.name === "tab") {
            cycleMode();
            event.preventDefault();
            return;
        }
        // The mention menu and the command menu never share the composer, but
        // they do share the selection index, so whichever is showing wins.
        if (mentions.length > 0) {
            if (event.name === "up") {
                setSelectedIndex((i) => Math.max(0, i - 1));
                event.preventDefault();
                return;
            }
            if (event.name === "down") {
                setSelectedIndex((i) => Math.min(mentions.length - 1, i + 1));
                event.preventDefault();
                return;
            }
            if (event.name === "escape") {
                setMentions([]);
                event.preventDefault();
                return;
            }
            if (event.name === "tab") {
                const item = mentions[selectedIndex] ?? mentions[0];
                if (item) acceptMention(item);
                event.preventDefault();
                return;
            }
        }
        if (suggestions.length > 0) {
            if (event.name === "up") {
                setSelectedIndex((i) => Math.max(0, i - 1));
                event.preventDefault();
                return;
            }
            if (event.name === "down") {
                setSelectedIndex((i) =>
                    Math.min(suggestions.length - 1, i + 1),
                );
                event.preventDefault();
                return;
            }
            if (event.name === "escape") {
                setSuggestions([]);
                event.preventDefault();
                return;
            }
            if (event.name === "tab") {
                const item = suggestions[0];
                if (item) {
                    textareaRef.current?.setText(`${item.usage} `);
                    refreshSuggestions(`${item.usage} `);
                }
                event.preventDefault();
                return;
            }
        }
        // Recall from a single-line composer, and keep going while already
        // recalling: a recalled multi-line prompt must not trap the arrows.
        const input = textareaRef.current;
        const value = input?.plainText ?? "";
        if (
            input &&
            (!value.includes("\n") || isNavigatingHistory())
        ) {
            if (event.name === "up") {
                const previous = historyUp(value);
                if (previous !== null) {
                    navigatingHistory.current = true;
                    input.setText(previous);
                    input.cursorOffset = previous.length;
                    event.preventDefault();
                    return;
                }
            }
            if (event.name === "down") {
                const next = historyDown();
                if (next !== null) {
                    navigatingHistory.current = true;
                    input.setText(next);
                    input.cursorOffset = next.length;
                    event.preventDefault();
                    return;
                }
            }
        }
        if (event.name === "escape") {
            // Both this handler and the global one in App fire for one keypress; the guard in requestInterrupt keeps it to one post.
            void requestInterrupt();
        }
    }

    const card = variant === "card";
    // One popup serves both menus; the mention list wins because a `@` token and
    // a leading `/` cannot be active in the same composer text.
    const menuItems: CommandSpec[] = mentions.length
        ? mentions.map((item) => ({
              id: item.value,
              label: item.label,
              description: item.hint,
              usage: item.label,
              aliases: [],
          }))
        : suggestions;
    // The root paints the menu (see MenuOverlay); the composer only owns its
    // state. Publishing here keeps one source of truth for which row is
    // selected.
    const menuKey = `${menuItems.length}:${selectedIndex}`;
    // Only the instance that published may clear: with a second composer mounted
    // (tests, or a future split view) an empty one would wipe a live menu.
    const publishedMenu = useRef(false);
    useEffect(() => {
        if (menuItems.length === 0) {
            if (publishedMenu.current) {
                publishedMenu.current = false;
                useMenuStore.getState().clear(instanceId.current);
            }
            return;
        }
        publishedMenu.current = true;
        const rows = Math.min(MENU_ROWS, menuItems.length);
        const box = boxRef.current;
        useMenuStore
            .getState()
            .show(
                menuItems,
                selectedIndex,
                rows + MENU_CHROME,
                {
                    x: box?.x ?? 0,
                    y: box?.y ?? 0,
                    width: box?.width ?? 0,
                    // Flush against the composer's outer top edge. In the card
                    // layout the composer sits one row inside the frame's
                    // border, so the menu has to stop one row higher.
                    edgeY: (box?.y ?? 0) - (card ? 1 : 0),
                },
                instanceId.current,
            );
    }, [menuKey]);

    // The composer moves when the textarea grows and when a turn ends. Poll the
    // measured box while the menu is open, the same way opencode does it (50 ms);
    // a stale anchor leaves the menu floating in the wrong place.
    const menuOpen = menuItems.length > 0;
    useEffect(() => {
        if (!menuOpen) return;
        const update = (): void => {
            const box = boxRef.current;
            if (!box) return;
            useMenuStore
                .getState()
                .setAnchor({
                    x: box.x,
                    y: box.y,
                    width: box.width,
                    edgeY: box.y - (card ? 1 : 0),
                });
        };
        update();
        const timer = setInterval(update, 50);
        return () => clearInterval(timer);
    }, [menuOpen]);

    // A menu that outlives the composer would hang over the next screen.
    useEffect(
        () => () => useMenuStore.getState().clear(instanceId.current),
        [],
    );

    // Pointer handlers for the root-painted menu. Kept in a ref so a click sees
    // the menu that is on screen now, not the one that existed at mount.
    const pickRef = useRef<(index: number) => void>(() => {});
    pickRef.current = (index: number): void => {
        // The mention list and the command list are built from different sources;
        // the same index means a different row in each.
        if (mentions.length > 0) {
            const mention = mentions[index];
            if (mention) acceptMention(mention);
            return;
        }
        const item = menuItems[index];
        if (!item) return;
        const parsed = parseCommand(item.usage);
        if (parsed) {
            clearComposer();
            onCommand(parsed.id, parsed.args);
        }
    };
    useEffect(() => {
        useMenuStore.getState().setHandlers({
            owner: instanceId.current,
            hover: (index) => setSelectedIndex(index),
            pick: (index) => pickRef.current(index),
        });
    }, []);

    return (
        <box
            ref={boxRef}
            flexDirection="column"
            flexShrink={0}
            paddingX={card ? 2 : 1}
            paddingY={card ? 1 : 0}
            marginTop={0}
            marginBottom={0}
            gap={0}
            {...(card
                ? {}
                : {
                      border: ["top", "bottom"] as const,
                      borderStyle: "single" as const,
                      borderColor: theme.text.muted,
                  })}
        >
            <box flexDirection="row" flexGrow={1}>
                <text fg={theme.primary.muted} content="> " height={textareaHeight} />
                <textarea
                    ref={textareaRef}
                    flexGrow={1}
                    focused
                    placeholder={placeholder}
                    placeholderColor={theme.text.faint}
                    textColor={theme.text.base}
                    focusedTextColor={theme.text.base}
                    keyBindings={COMPOSER_KEY_BINDINGS}
                    syntaxStyle={mentionStyle ?? undefined}
                    onSubmit={submitCurrent}
                    onContentChange={() => {
                        const value = textareaRef.current?.plainText ?? "";
                        // Our own setText must not be mistaken for new typing,
                        // which would drop the recall position.
                        if (navigatingHistory.current) {
                            navigatingHistory.current = false;
                        } else {
                            resetHistoryCursor();
                        }
                        refreshSuggestions(value);
                        syncAttachments();
                    }}
                    onPaste={handlePaste}
                    onKeyDown={handleKeyDown}
                    wrapMode="word"
                    height={textareaHeight}
                />
            </box>
        </box>
    );
}
