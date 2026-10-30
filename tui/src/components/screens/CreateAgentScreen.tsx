/** Create Agent screen: key → name → description → parents → create.
 *
 *  The parent step is what decides whether the record is a sub-agent: the backend
 *  sets mode=subagent whenever parent_ids is supplied, and a child that belongs
 *  to no primary agent never appears in anyone's roster.
 */
import { useEffect, useRef, useState } from "react";
import { useKeyboard } from "@opentui/react";
import type { InputRenderable } from "@opentui/core";
import { createAgent, listAgents } from "../../api/nova-api.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { useTheme } from "../../context/theme.tsx";
import { ScreenPanel } from "./ScreenPanel.tsx";

const FIELDS = [
    { key: "key", label: "Agent key (3-32 chars: [a-z0-9-])", required: true },
    { key: "name", label: "Display name", required: true },
    { key: "description", label: "Description (optional)", required: false },
] as const;

type FieldKey = (typeof FIELDS)[number]["key"];
type Values = Record<FieldKey, string>;

/** Rows visible at once in the parent picker; the cursor scrolls the window. */
const PARENT_ROWS = 8;

type ParentOption = { key: string; name: string };

export function CreateAgentScreen() {
    const theme = useTheme();
    const [step, setStep] = useState(0);
    const [values, setValues] = useState<Values>({
        key: "",
        name: "",
        description: "",
    });
    const [error, setError] = useState("");
    const [parents, setParents] = useState<ParentOption[]>([]);
    const [selected, setSelected] = useState<string[]>([]);
    const [cursor, setCursor] = useState(0);
    const inputRef = useRef<InputRenderable>(null);

    const pickingParents = step === FIELDS.length;
    // The render below only reaches `field` when the step is still an input one.
    const field = FIELDS[step]!;

    useEffect(() => {
        let cancelled = false;
        void listAgents()
            .then((agents) => {
                if (cancelled) return;
                setParents(
                    agents
                        // A sub-agent cannot parent another one; only primaries
                        // are offered.
                        .filter((agent) => agent.kind !== "sub")
                        .map((agent) => ({ key: agent.key, name: agent.name })),
                );
            })
            .catch(() => {
                // An empty picker only costs the parent step; creating a plain
                // agent must still work.
            });
        return () => {
            cancelled = true;
        };
    }, []);

    function moveCursor(delta: number): void {
        if (parents.length === 0) return;
        setCursor((index) =>
            Math.min(Math.max(index + delta, 0), parents.length - 1),
        );
    }

    function toggle(key: string | undefined): void {
        if (!key) return;
        setSelected((current) =>
            current.includes(key)
                ? current.filter((item) => item !== key)
                : [...current, key],
        );
    }

    async function submit(
        valuesToUse: Values,
        parentKeys: string[],
    ): Promise<void> {
        if (!valuesToUse.key || !valuesToUse.name) {
            return;
        }
        useScreenStore.getState().close();
        try {
            await createAgent({
                key: valuesToUse.key,
                name: valuesToUse.name,
                description: valuesToUse.description,
                // Only sent when something is picked, so the same screen still
                // creates a primary agent.
                ...(parentKeys.length > 0 ? { parent_ids: parentKeys } : {}),
            });
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        }
    }

    useKeyboard((key) => {
        if (key.name === "escape") {
            useScreenStore.getState().close();
            return;
        }
        if (!pickingParents) {
            return;
        }
        if (key.name === "up") {
            moveCursor(-1);
            return;
        }
        if (key.name === "down") {
            moveCursor(1);
            return;
        }
        // Both spellings occur across platforms; the ask-user card accepts both.
        if (key.name === "space" || key.name === " ") {
            toggle(parents[cursor]?.key);
            return;
        }
        if (key.name === "return" || key.name === "enter") {
            void submit(values, selected);
        }
    });

    if (pickingParents) {
        const start = Math.max(
            0,
            Math.min(cursor - Math.floor(PARENT_ROWS / 2), parents.length - PARENT_ROWS),
        );
        const visible = parents.slice(start, start + PARENT_ROWS);
        return (
            <ScreenPanel width="60%">
                <text fg={theme.primary.muted}>
                    Create Agent — Parents (optional)
                </text>
                {parents.length === 0 ? (
                    <text
                        fg={theme.text.muted}
                        content="No primary agents to attach to."
                    />
                ) : (
                    <box flexDirection="column">
                        {visible.map((option, index) => {
                            const active = start + index === cursor;
                            const picked = selected.includes(option.key);
                            return (
                                <text
                                    key={option.key}
                                    fg={
                                        active
                                            ? theme.primary.base
                                            : theme.text.base
                                    }
                                    content={`${active ? ">" : " "} [${
                                        picked ? "x" : " "
                                    }] ${option.key}  ${option.name}`}
                                />
                            );
                        })}
                    </box>
                )}
                <text
                    fg={theme.text.muted}
                    content={`selected: ${selected.length}`}
                />
                <text
                    fg={theme.text.muted}
                    content="space toggles • enter creates • esc cancels"
                />
                <text
                    fg={theme.text.faint}
                    content="Leave empty to create a normal primary agent."
                />
                {error ? <text fg={theme.feedback.error} content={error} /> : null}
            </ScreenPanel>
        );
    }

    return (
        <ScreenPanel width="60%">
            <text fg={theme.primary.muted}>Create Agent — {field.label}</text>
            <input
                ref={inputRef}
                flexGrow={1}
                focused
                placeholder={
                    field.key === "key"
                        ? "my-agent"
                        : field.key === "name"
                          ? "My Agent"
                          : "(optional)"
                }
                placeholderColor={theme.text.faint}
                textColor={theme.text.base}
                focusedTextColor={theme.text.base}
                onSubmit={() => {
                    const value = inputRef.current?.value ?? "";
                    const next: Values = { ...values, [field.key]: value };
                    setValues(next);
                    if (field.required && !value.trim()) {
                        return;
                    }
                    if (step < FIELDS.length - 1) {
                        inputRef.current?.clear();
                        setStep(step + 1);
                        return;
                    }
                    // The parent step decides sub-agent vs primary; blur so the
                    // input does not swallow the list's keys.
                    inputRef.current?.blur();
                    setStep(FIELDS.length);
                }}
            />
            {error ? <text fg={theme.feedback.error} content={error} /> : null}
            <text fg={theme.text.muted}>
                {step + 1}/{FIELDS.length + 1} • enter next • esc cancel
            </text>
        </ScreenPanel>
    );
}
