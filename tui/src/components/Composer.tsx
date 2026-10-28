/** Bottom input area: multi-line textarea, Enter to submit, Shift+Enter for newline, slash command suggestions, ESC to interrupt */
import {
    decodePasteBytes,
    type KeyBinding,
    type KeyEvent,
    type PasteEvent,
    type TextareaRenderable,
} from "@opentui/core";
import { useEffect, useRef, useState } from "react";
import { interruptChat } from "../api/nova-api.ts";
import {
    displayPath,
    resolvePastedFiles,
    toNovaAttachment,
    type PastedFile,
} from "../lib/attachments.ts";
import { truncateMiddle } from "../lib/display-width.ts";
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
import { runChatStream } from "../stream/chat-stream.ts";
import { useTheme } from "../context/theme.tsx";
import { CommandSuggestions } from "./CommandSuggestions.tsx";

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
    const sessionId = useChatStore((state) => state.sessionId);
    const askActive = useAskUserStore((state) => state.active) !== null;
    const approvalPending = useApprovalStore((state) => state.pending) !== null;
    const screenCurrent = useScreenStore((state) => state.current) !== null;
    // Keep these calls separate: `||` would skip the later store hooks when an
    // earlier modal is open, desyncing React's hook chain.
    const modalOpen = askActive || approvalPending || screenCurrent;
    const textareaRef = useRef<TextareaRenderable>(null);
    const [suggestions, setSuggestions] = useState<CommandSpec[]>([]);
    const [selectedIndex, setSelectedIndex] = useState(0);
    const [textareaHeight, setTextareaHeight] = useState(TEXTAREA_MIN_HEIGHT);
    // Keyed by the extmark that draws the chip: opentui deletes a virtual
    // extmark as a whole, so the attachment disappears with its label.
    const [attachments, setAttachments] = useState<
        { extmarkId: number; file: PastedFile }[]
    >([]);
    const attachmentType = useRef<number | null>(null);

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
            setSelectedIndex(0);
        } else {
            setSuggestions([]);
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

    function clearComposer(): void {
        textareaRef.current?.clear();
        setSuggestions([]);
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
        if (event.name === "escape" && isStreaming && sessionId) {
            void interruptChat(sessionId);
        }
    }

    const card = variant === "card";
    return (
        <box
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
            <CommandSuggestions
                items={suggestions}
                selectedIndex={selectedIndex}
            />
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
                    onSubmit={submitCurrent}
                    onContentChange={() => {
                        const value = textareaRef.current?.plainText ?? "";
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
