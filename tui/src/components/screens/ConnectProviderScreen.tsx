/** Connect a provider: pick a vendor, answer what it still needs, done.
 *
 *  Connecting is the whole action in the TUI. The backend saves every model the
 *  provider advertises as part of the create call, so there is no follow-up
 *  step and no model to add by hand — this screen exists because reaching into
 *  config.json was the only way to get a provider into a terminal session.
 */
import { useEffect, useRef, useState } from "react";
import { useKeyboard } from "@opentui/react";
import type { InputRenderable } from "@opentui/core";
import {
    createProvider,
    deleteProvider,
    listProviderPresets,
    listProviders,
    updateProvider,
} from "../../api/nova-api.ts";
import type { NovaProviderPreset } from "../../api/types.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { useToastStore } from "../../stores/toast-store.ts";
import { useApp } from "../../context/app.tsx";
import { useTheme } from "../../context/theme.tsx";
import { ScreenPanel } from "./ScreenPanel.tsx";
import { SearchableList } from "./SearchableList.tsx";

const CUSTOM_ID = "__custom__";

type FieldName = "providerKey" | "apiKey" | "baseUrl";

type Choice = {
    id: string;
    label: string;
    type: string;
    base_url: string;
    key_env: string | null;
    custom: boolean;
};

const CUSTOM: Choice = {
    id: CUSTOM_ID,
    label: "Custom (any OpenAI-compatible endpoint)",
    type: "openai-compatible",
    base_url: "",
    key_env: null,
    custom: true,
};

const LABELS: Record<FieldName, string> = {
    providerKey: "Provider key",
    apiKey: "API key",
    baseUrl: "Base URL",
};

const HINTS: Record<FieldName, string> = {
    providerKey: "a short name you will recognise, e.g. my-gateway",
    apiKey: "paste the key; it is written to config.json, not to the transcript",
    baseUrl: "https://your-endpoint/v1",
};

/** Local presets need no key, so choosing one submits straight away. */
function fieldsFor(choice: Choice): FieldName[] {
    if (choice.custom) return ["providerKey", "apiKey", "baseUrl"];
    return choice.key_env ? ["apiKey"] : [];
}

export function ConnectProviderScreen() {
    const theme = useTheme();
    const { reloadCatalog } = useApp();
    const [presets, setPresets] = useState<Choice[]>([]);
    const [connected, setConnected] = useState<Set<string>>(new Set());
    const [authenticated, setAuthenticated] = useState<Set<string>>(new Set());
    const [loaded, setLoaded] = useState(false);
    const [choice, setChoice] = useState<Choice | null>(null);
    // A connected provider opens on its own panel first: updating a key and
    // removing one are different intents, and the second one needs a
    // shortcut that cannot be typed into the filter.
    const [detail, setDetail] = useState<Choice | null>(null);
    const [values, setValues] = useState<Record<FieldName, string>>({
        providerKey: "",
        apiKey: "",
        baseUrl: "",
    });
    const [step, setStep] = useState(0);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState("");
    const inputRef = useRef<InputRenderable>(null);

    useEffect(() => {
        let cancelled = false;
        void Promise.all([
            listProviderPresets(),
            // Knowing what is already connected is a nicety: without it the
            // screen still works, it just cannot draw the check mark.
            listProviders().catch(() => []),
        ])
            .then(([items, providers]) => {
                if (cancelled) return;
                setConnected(
                    new Set(providers.map((provider: { key: string }) => provider.key)),
                );
                // The check mark means "Nova holds a key for this on this
                // machine". A provider authored in config.json is usable, but
                // it is not something /connect did, so it stays unmarked.
                setAuthenticated(
                    new Set(
                        providers
                            .filter(
                                (provider: { authenticated?: boolean }) =>
                                    provider.authenticated,
                            )
                            .map((provider: { key: string }) => provider.key),
                    ),
                );
                setPresets([
                    ...items.map((preset: NovaProviderPreset) => ({
                        id: preset.id,
                        label: preset.label,
                        type: preset.type,
                        base_url: preset.base_url,
                        key_env: preset.key_env,
                        custom: preset.custom === true,
                    })),
                    CUSTOM,
                ]);
                setLoaded(true);
            })
            .catch((err) => {
                if (cancelled) return;
                setError(err instanceof Error ? err.message : String(err));
                setLoaded(true);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    async function disconnect(target: Choice) {
        setSaving(true);
        setError("");
        try {
            await deleteProvider(target.id);
            await reloadCatalog().catch(() => {});
            setAuthenticated((current) => {
                const next = new Set(current);
                next.delete(target.id);
                return next;
            });
            setConnected((current) => {
                const next = new Set(current);
                next.delete(target.id);
                return next;
            });
            useToastStore.getState().show(`Disconnected ${target.id}`);
            setDetail(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        } finally {
            setSaving(false);
        }
    }

    async function submit(target: Choice, filled: Record<FieldName, string>) {
        const providerKey = target.custom
            ? filled.providerKey.trim()
            : target.id;
        if (!providerKey) {
            setError("Provider key is required.");
            return;
        }
        if (connected.has(providerKey) && !filled.apiKey.trim()) {
            useToastStore.getState().show(`${providerKey} is already connected`);
            useScreenStore.getState().close();
            return;
        }
        setSaving(true);
        setError("");
        try {
            const already = connected.has(providerKey);
            const { models, warning } = already
                ? {
                      models: await updateProvider(providerKey, {
                          api_key: filled.apiKey.trim(),
                      }),
                      warning: null,
                  }
                : await createProvider({
                      key: providerKey,
                      type: target.type,
                      name: target.custom ? providerKey : target.label,
                      base_url: target.custom
                          ? filled.baseUrl.trim()
                          : target.base_url,
                      api_key: filled.apiKey.trim(),
                      custom: target.custom,
                  });
            const found = models.filter(
                (model) => model.provider === providerKey,
            ).length;
            // The model list is cached for the process lifetime, so without this
            // the toast would count models the picker cannot show yet. A failed
            // refetch must not turn a saved provider into an error: the write
            // already happened.
            await reloadCatalog().catch(() => {});
            useToastStore
                .getState()
                .show(
                    warning
                        ? `${providerKey} saved · ${warning}`
                        : `Connected ${providerKey} · ${found} model(s) ready`,
                );
            useScreenStore.getState().close();
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        } finally {
            setSaving(false);
        }
    }

    function choose(target: Choice) {
        setChoice(target);
        setError("");
        const fields = fieldsFor(target);
        setStep(0);
        if (fields.length === 0) {
            void submit(target, values);
        }
    }

    /** Group order: what you can add, what you have, then the escape hatch. */
    function rank(target: Choice): number {
        if (target.custom) return 2;
        if (connected.has(target.id)) return 1;
        return 0;
    }

    function fieldsForChoice(target: Choice): FieldName[] {
        // Reconnecting an existing provider can only mean a new key; its
        // transport is already settled, custom or not.
        if (connected.has(target.id)) {
            if (target.custom) return ["apiKey"];
            return target.key_env ? ["apiKey"] : [];
        }
        return fieldsFor(target);
    }

    // The list owns its own keys, including the escape that closes the screen.
    // Once a provider is picked, this handler owns the stage.
    useKeyboard((key) => {
        if (detail) {
            if (key.name === "escape") {
                setDetail(null);
                return;
            }
            if (key.ctrl && key.name === "d") {
                void disconnect(detail);
                return;
            }
            if (key.name === "return" || key.name === "enter") {
                choose(detail);
            }
            return;
        }
        if (choice && key.name === "escape") {
            useScreenStore.getState().close();
        }
    });

    if (detail) {
        return (
            <ScreenPanel width="50%">
                <box flexDirection="column" gap={1}>
                    <box flexDirection="row" justifyContent="space-between">
                        <text fg={theme.primary.muted} content={detail.label} />
                        <text fg={theme.text.faint} content="esc" />
                    </box>
                    <text fg={theme.text.base} content="● Connected · API key" />
                    {detail.base_url ? (
                        <text fg={theme.text.faint} content={detail.base_url} />
                    ) : null}
                    {error ? (
                        <text fg={theme.feedback.error} content={error} />
                    ) : null}
                    <text
                        fg={theme.text.muted}
                        content={
                            saving
                                ? "working…"
                                : "⏎ update key    ctrl+d disconnect"
                        }
                    />
                </box>
            </ScreenPanel>
        );
    }

    if (!loaded) {
        return (
            <ScreenPanel width="60%">
                <text
                    fg={theme.text.muted}
                    content={error || "Loading providers..."}
                />
            </ScreenPanel>
        );
    }

    if (!choice) {
        // Shared with every other picker: 44 vendors are unusable without a
        // filter, and the list already owns the cursor, the paging and escape.
        return (
            <SearchableList
                title="Connect a provider · ✓ key stored"
                items={[...presets]
                    // SearchableList draws a header whenever the group changes,
                    // so an unsorted list repeats them every few rows.
                    .sort((a, b) => rank(a) - rank(b))
                    .map((preset) => ({
                        label: preset.label,
                        value: preset.id,
                        group: preset.custom
                            ? "Custom"
                            : connected.has(preset.id)
                              ? "Configured"
                              : "Available",
                        typeLabel: preset.custom ? "" : preset.type,
                        checked: authenticated.has(preset.id),
                    }))}
                // Name only. Matching the wire type turned "anthropic" into a
                // list of everything that speaks it, which is not what anyone
                // types into this box.
                filter={(item, query) => {
                    const needle = query.toLowerCase();
                    return (
                        item.label.toLowerCase().includes(needle) ||
                        item.value.includes(needle)
                    );
                }}
                // The check lives in the cursor column, like the dot in the
                // models screen: same width, so every row still starts at the
                // column the title and the group headers use.
                marker={(item) => (item.checked ? "✓" : undefined)}
                renderLabel={(item) =>
                    `${item.label}${
                        item.typeLabel ? "  ·  " + item.typeLabel : ""
                    }`
                }
                onSelect={(value) => {
                    const target = presets.find((item) => item.id === value);
                    if (!target) return;
                    if (authenticated.has(target.id)) {
                        setDetail(target);
                        return;
                    }
                    choose(target);
                }}
                onClose={() => useScreenStore.getState().close()}
                emptyText="no matching provider"
            />
        );
    }

    const fields = fieldsForChoice(choice);
    const field = fields[step] ?? fields[0]!;
    const last = step === fields.length - 1;

    return (
        <ScreenPanel width="50%">
            <box flexDirection="column" gap={1}>
                <text fg={theme.primary.muted} content={choice.label} />
                {choice.custom ? null : (
                    <text
                        fg={theme.text.faint}
                        content={choice.base_url || "(adapter default)"}
                    />
                )}
                <text
                    fg={theme.text.faint}
                    content={`${LABELS[field]} · ${HINTS[field]}`}
                />
                <input
                    key={field}
                    ref={inputRef}
                    focused
                    value={values[field]}
                    placeholder={field === "providerKey" ? "my-gateway" : ""}
                    placeholderColor={theme.text.faint}
                    textColor={theme.text.base}
                    focusedTextColor={theme.text.base}
                    onInput={(text) =>
                        setValues((current) => ({
                            ...current,
                            [field]: text,
                        }))
                    }
                    onSubmit={() => {
                        if (saving) return;
                        if (last) {
                            void submit(choice, values);
                        } else {
                            setStep((current) => current + 1);
                        }
                    }}
                />
                {error ? (
                    <text fg={theme.feedback.error} content={error} />
                ) : null}
                <text
                    fg={theme.text.faint}
                    content={saving ? "connecting…" : last ? "⏎ connect · esc cancel" : "⏎ next · esc cancel"}
                />
            </box>
        </ScreenPanel>
    );
}
