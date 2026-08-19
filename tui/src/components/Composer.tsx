/** Bottom input area: multi-line textarea, Enter to submit, Shift+Enter for newline, slash command suggestions, ESC to interrupt */
import type { KeyBinding, KeyEvent, TextareaRenderable } from "@opentui/core";
import { useEffect, useRef, useState } from "react";
import { interruptChat } from "../api/nova-api.ts";
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
import { CommandSuggestions } from "./CommandSuggestions.tsx";

const COMPOSER_KEY_BINDINGS: KeyBinding[] = [
    { name: "enter", action: "submit" },
    { name: "enter", shift: true, action: "newline" },
];

const TEXTAREA_MIN_HEIGHT = 1;
const TEXTAREA_MAX_HEIGHT = 12;

export type ComposerCommandHandler = (id: string, args: string) => void;

export function Composer({ onCommand }: { onCommand: ComposerCommandHandler }) {
    const isStreaming = useChatStore((state) => state.isStreaming);
    const sessionId = useChatStore((state) => state.sessionId);
    const modalOpen =
        useAskUserStore((state) => state.active) !== null ||
        useApprovalStore((state) => state.pending) !== null ||
        useScreenStore((state) => state.current) !== null;
    const textareaRef = useRef<TextareaRenderable>(null);
    const [suggestions, setSuggestions] = useState<CommandSpec[]>([]);
    const [selectedIndex, setSelectedIndex] = useState(0);
    const [textareaHeight, setTextareaHeight] = useState(TEXTAREA_MIN_HEIGHT);

    useEffect(() => {
        if (modalOpen) {
            textareaRef.current?.blur();
        } else {
            textareaRef.current?.focus();
        }
    }, [modalOpen]);

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
        clearComposer();
        await runChatStream({ message: value });
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

    return (
        <box
            flexDirection="column"
            flexShrink={0}
            paddingX={1}
            border={["top", "bottom"]}
            borderStyle="single"
            borderColor="#444c56"
        >
            <CommandSuggestions
                items={suggestions}
                selectedIndex={selectedIndex}
            />
            <box flexDirection="row" flexGrow={1}>
                <text fg="#4f9cf9" content="> " height={textareaHeight} />
                <textarea
                    ref={textareaRef}
                    flexGrow={1}
                    focused
                    placeholder="Message Nova (Enter to send, Shift+Enter for newline)"
                    placeholderColor="#6e7681"
                    keyBindings={COMPOSER_KEY_BINDINGS}
                    onSubmit={submitCurrent}
                    onContentChange={() => {
                        const value = textareaRef.current?.plainText ?? "";
                        refreshSuggestions(value);
                    }}
                    onKeyDown={handleKeyDown}
                    wrapMode="word"
                    height={textareaHeight}
                />
            </box>
        </box>
    );
}
