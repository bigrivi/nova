import type {
    NovaModelRecord,
    NovaProviderPreset,
    NovaProviderRecord,
} from "../../../types/nova";

export type { NovaModelRecord, NovaProviderPreset, NovaProviderRecord };

export type ModelsManagerDialogProps = {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    providers: NovaProviderRecord[];
    models: NovaModelRecord[];
    onModelsUpdated: (models: NovaModelRecord[]) => void;
    onProvidersRefresh: () => Promise<void>;
    onStatusChange: (message: string | null) => void;
};

export type ProviderFormState = {
    key: string;
    type: "ollama" | "openai-compatible" | "openai-response" | "anthropic";
    name: string;
    baseUrl: string;
    apiKey: string;
};

export type ModelFormState = {
    provider: string;
    model: string;
    label: string;
    tools: boolean;
};

export type ProviderEditState = {
    name: string;
    type: "ollama" | "openai-compatible" | "openai-response" | "anthropic";
    baseUrl: string;
    apiKey: string;
};

export const PROVIDER_TYPE_VALUES = [
    "openai-compatible",
    "openai-response",
    "anthropic",
    "ollama",
] as const;

export const PROVIDER_TYPE_LABEL_KEYS: Record<
    ProviderFormState["type"],
    string
> = {
    "openai-compatible": "modelSelector.openaiCompatible",
    "openai-response": "modelSelector.openaiResponse",
    anthropic: "modelSelector.anthropic",
    ollama: "modelSelector.ollama",
};

export const PROVIDER_TYPE_PLACEHOLDER_KEYS: Record<
    ProviderFormState["type"],
    string
> = {
    "openai-compatible": "modelSelector.baseUrlPlaceholderOpenai",
    "openai-response": "modelSelector.baseUrlPlaceholderOpenai",
    anthropic: "modelSelector.baseUrlPlaceholderAnthropic",
    ollama: "modelSelector.baseUrlPlaceholderOllama",
};

export function defaultProviderState(): ProviderFormState {
    return {
        key: "",
        type: "openai-compatible",
        name: "",
        baseUrl: "",
        apiKey: "",
    };
}

export function defaultModelState(
    providers: NovaProviderRecord[],
): ModelFormState {
    return {
        provider: providers[0]?.key ?? "",
        model: "",
        label: "",
        tools: true,
    };
}

export function toEditState(
    provider: NovaProviderRecord | undefined,
): ProviderEditState {
    const rawType = provider?.type ?? "openai-compatible";
    const type = (
        rawType === "ollama" || rawType === "anthropic"
            ? rawType
            : "openai-compatible"
    ) as ProviderEditState["type"];
    return {
        name: provider?.name ?? "",
        type,
        baseUrl: provider?.base_url ?? "",
        apiKey: "",
    };
}

export const inputClassName =
    "h-9 w-full rounded-lg border bg-background px-3 text-base outline-none focus:border-ring focus:ring-2 focus:ring-ring/20 sm:text-sm";
