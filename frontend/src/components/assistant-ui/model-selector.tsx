import { PlusIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "../ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import { createModel, createProvider } from "../../lib/nova-api";
import type {
  NovaModelRecord,
  NovaProviderRecord,
} from "../../types/nova";

type ModelSelectorProps = {
  models: NovaModelRecord[];
  providers: NovaProviderRecord[];
  selectedModelId: string | null;
  onSelect: (modelId: string) => void;
  onModelsUpdated: (models: NovaModelRecord[]) => void;
  onProvidersRefresh: () => Promise<void>;
  onStatusChange: (message: string | null) => void;
  compact?: boolean;
};

type ModelGroup = {
  provider: string;
  providerName: string;
  models: NovaModelRecord[];
};

type ProviderFormState = {
  key: string;
  type: "ollama" | "openai-compatible";
  name: string;
  baseUrl: string;
  apiKey: string;
};

type ModelFormState = {
  provider: string;
  model: string;
  label: string;
  tools: boolean;
};

const PROVIDER_TYPE_OPTIONS = [
  {
    value: "ollama" as const,
    label: "Ollama",
  },
  {
    value: "openai-compatible" as const,
    label: "OpenAI Compatible",
  },
];

function groupModels(models: NovaModelRecord[]): ModelGroup[] {
  const groups = new Map<string, ModelGroup>();

  for (const model of models) {
    const existing = groups.get(model.provider);
    if (existing) {
      existing.models.push(model);
      continue;
    }

    groups.set(model.provider, {
      provider: model.provider,
      providerName: model.provider_name,
      models: [model],
    });
  }

  return [...groups.values()];
}

function renderGroupedItems(groups: ModelGroup[]) {
  return groups.flatMap((group, index) => {
    const parts = [
      <SelectGroup key={group.provider}>
        <SelectLabel className="px-2.5 pb-1 pt-2 font-semibold text-[10px] uppercase tracking-[0.14em] text-foreground/65">
          {group.providerName}
        </SelectLabel>
        {group.models.map((model) => (
          <SelectItem key={model.id} value={model.id} className="pl-5">
            <span className="inline-block pl-1">{model.label}</span>
          </SelectItem>
        ))}
      </SelectGroup>,
    ];

    if (index < groups.length - 1) {
      parts.push(
        <SelectSeparator key={`${group.provider}-separator`} className="my-1.5" />,
      );
    }

    return parts;
  });
}

function defaultProviderState(): ProviderFormState {
  return {
    key: "",
    type: "openai-compatible",
    name: "",
    baseUrl: "",
    apiKey: "",
  };
}

function defaultModelState(providers: NovaProviderRecord[]): ModelFormState {
  return {
    provider: providers[0]?.key ?? "",
    model: "",
    label: "",
    tools: true,
  };
}

type DialogActionsProps = {
  children: React.ReactNode;
};

function DialogActions({ children }: DialogActionsProps) {
  return <DialogFooter className="gap-2">{children}</DialogFooter>;
}

export function ModelSelector({
  models,
  providers,
  selectedModelId,
  onSelect,
  onModelsUpdated,
  onProvidersRefresh,
  onStatusChange,
  compact = false,
}: ModelSelectorProps) {
  const [isProviderDialogOpen, setIsProviderDialogOpen] = useState(false);
  const [isModelDialogOpen, setIsModelDialogOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [providerForm, setProviderForm] = useState<ProviderFormState>(
    defaultProviderState(),
  );
  const [modelForm, setModelForm] = useState<ModelFormState>(
    defaultModelState(providers),
  );
  const [providerError, setProviderError] = useState<string | null>(null);
  const [modelError, setModelError] = useState<string | null>(null);

  const hasModels = models.length > 0;
  const hasProviders = providers.length > 0;
  const selectId = compact ? "nova-model-select-inline" : "nova-model-select";
  const groupedModels = useMemo(() => groupModels(models), [models]);
  const selectedModel =
    models.find((model) => model.id === selectedModelId) ?? models[0] ?? null;
  const selectedValue = selectedModel?.id;

  function openProviderDialog() {
    setProviderError(null);
    setIsProviderDialogOpen(true);
  }

  function openModelDialog() {
    setModelError(null);
    setModelForm((current) => ({
      ...current,
      provider: current.provider || providers[0]?.key || "",
    }));
    setIsModelDialogOpen(true);
  }

  useEffect(() => {
    setModelForm((current) => {
      if (current.provider || providers.length === 0) {
        return current;
      }
      return {
        ...current,
        provider: providers[0].key,
      };
    });
  }, [providers]);

  function resetProviderDialog() {
    setProviderForm(defaultProviderState());
    setProviderError(null);
    setIsProviderDialogOpen(false);
  }

  function resetModelDialog() {
    setModelForm(defaultModelState(providers));
    setModelError(null);
    setIsModelDialogOpen(false);
  }

  async function handleProviderSubmit() {
    setProviderError(null);
    onStatusChange(null);
    setIsSubmitting(true);
    try {
      const nextModels = await createProvider({
        key: providerForm.key,
        type: providerForm.type,
        name: providerForm.name,
        base_url: providerForm.baseUrl,
        api_key: providerForm.apiKey,
      });
      await onProvidersRefresh();
      onModelsUpdated(nextModels);
      resetProviderDialog();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setProviderError(message);
      onStatusChange(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleModelSubmit() {
    setModelError(null);
    onStatusChange(null);
    setIsSubmitting(true);
    try {
      const nextModels = await createModel({
        provider: modelForm.provider,
        model: modelForm.model,
        label: modelForm.label,
        tools: modelForm.tools,
      });
      onModelsUpdated(nextModels);
      const createdModelId = `${modelForm.provider}:${modelForm.model}`;
      onSelect(createdModelId);
      resetModelDialog();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setModelError(message);
      onStatusChange(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  const selector = (
    <Select value={selectedValue} onValueChange={onSelect} disabled={!hasModels}>
      <SelectTrigger
        id={selectId}
        aria-label="Active model"
        title={selectedModel?.label || "No models available"}
        className={
          compact
            ? "h-8 w-32 rounded-full border-border/60 bg-background/85 px-2.5 py-0 text-[11px] font-medium text-muted-foreground shadow-none hover:bg-muted/35 focus:bg-background focus:text-foreground focus-visible:ring-ring/15 sm:w-36"
            : "h-10 w-full rounded-xl"
        }
      >
        <SelectValue placeholder="No models available" />
      </SelectTrigger>
      <SelectContent align={compact ? "end" : "center"}>
        {renderGroupedItems(groupedModels)}
      </SelectContent>
    </Select>
  );

  const actions = (
    <div className={compact ? "flex items-center gap-1.5" : "flex items-center gap-2"}>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size={compact ? "icon-sm" : "sm"}
            className={compact ? "rounded-full" : "rounded-xl"}
          >
            <PlusIcon className="size-3.5" />
            {!compact ? "Configure" : null}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-44">
          <DropdownMenuItem onSelect={openProviderDialog}>
            Add provider
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={openModelDialog}
            disabled={!hasProviders}
          >
            Add model
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );

  return (
    <>
      {compact ? (
        <div className="flex items-center gap-2">
          <label className="sr-only" htmlFor={selectId}>
            Active model
          </label>
          {selector}
          {actions}
        </div>
      ) : (
        <div className="space-y-3 rounded-2xl border bg-card p-4 shadow-sm">
          <div className="space-y-1">
            <label className="text-sm font-medium text-foreground" htmlFor={selectId}>
              Active model
            </label>
            <p className="text-xs leading-5 text-muted-foreground">
              The selected provider/model pair is sent as a per-request override to
              Nova&apos;s backend.
            </p>
          </div>
          <div className="flex flex-col gap-3">
            {selector}
            {actions}
          </div>
        </div>
      )}

      <Dialog open={isProviderDialogOpen} onOpenChange={setIsProviderDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add provider</DialogTitle>
            <DialogDescription>
              Save a new provider into Nova&apos;s config.json. Provider keys must be unique.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-foreground">Provider key</span>
              <input
                value={providerForm.key}
                onChange={(event) =>
                  setProviderForm((current) => ({ ...current, key: event.target.value }))
                }
                className="h-9 w-full rounded-lg border bg-background px-3 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"
                placeholder="openrouter"
              />
            </label>

            <label className="block space-y-1">
              <span className="text-xs font-medium text-foreground">Display name</span>
              <input
                value={providerForm.name}
                onChange={(event) =>
                  setProviderForm((current) => ({ ...current, name: event.target.value }))
                }
                className="h-9 w-full rounded-lg border bg-background px-3 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"
                placeholder="OpenRouter"
              />
            </label>

            <div className="space-y-1">
              <span className="text-xs font-medium text-foreground">Provider type</span>
              <Select
                value={providerForm.type}
                onValueChange={(value) =>
                  setProviderForm((current) => ({
                    ...current,
                    type: value as ProviderFormState["type"],
                  }))
                }
              >
                <SelectTrigger className="h-9 rounded-lg">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PROVIDER_TYPE_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <label className="block space-y-1">
              <span className="text-xs font-medium text-foreground">Base URL</span>
              <input
                value={providerForm.baseUrl}
                onChange={(event) =>
                  setProviderForm((current) => ({
                    ...current,
                    baseUrl: event.target.value,
                  }))
                }
                className="h-9 w-full rounded-lg border bg-background px-3 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"
                placeholder={
                  providerForm.type === "ollama"
                    ? "http://localhost:11434"
                    : "https://api.example.com/v1"
                }
              />
            </label>

            {providerForm.type === "openai-compatible" ? (
              <label className="block space-y-1">
                <span className="text-xs font-medium text-foreground">API key</span>
                <input
                  type="password"
                  value={providerForm.apiKey}
                  onChange={(event) =>
                    setProviderForm((current) => ({
                      ...current,
                      apiKey: event.target.value,
                    }))
                  }
                  className="h-9 w-full rounded-lg border bg-background px-3 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"
                  placeholder="sk-..."
                />
              </label>
            ) : null}

            {providerError ? (
              <p className="text-xs text-destructive">{providerError}</p>
            ) : null}
          </div>

          <DialogActions>
            <Button type="button" variant="outline" onClick={resetProviderDialog}>
              Cancel
            </Button>
            <Button type="button" disabled={isSubmitting} onClick={() => void handleProviderSubmit()}>
              Save provider
            </Button>
          </DialogActions>
        </DialogContent>
      </Dialog>

      <Dialog open={isModelDialogOpen} onOpenChange={setIsModelDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add model</DialogTitle>
            <DialogDescription>
              Save a new model under an existing provider. Model names must be unique within that provider.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div className="space-y-1">
              <span className="text-xs font-medium text-foreground">Provider</span>
              <Select
                value={modelForm.provider}
                onValueChange={(value) =>
                  setModelForm((current) => ({ ...current, provider: value }))
                }
              >
                <SelectTrigger className="h-9 rounded-lg">
                  <SelectValue placeholder="Select provider" />
                </SelectTrigger>
                <SelectContent>
                  {providers.map((provider) => (
                    <SelectItem key={provider.key} value={provider.key}>
                      {provider.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <label className="block space-y-1">
              <span className="text-xs font-medium text-foreground">Model key</span>
              <input
                value={modelForm.model}
                onChange={(event) =>
                  setModelForm((current) => ({ ...current, model: event.target.value }))
                }
                className="h-9 w-full rounded-lg border bg-background px-3 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"
                placeholder="gpt-5.4-mini"
              />
            </label>

            <label className="block space-y-1">
              <span className="text-xs font-medium text-foreground">Label</span>
              <input
                value={modelForm.label}
                onChange={(event) =>
                  setModelForm((current) => ({ ...current, label: event.target.value }))
                }
                className="h-9 w-full rounded-lg border bg-background px-3 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"
                placeholder="gpt-5.4-mini"
              />
            </label>

            <label className="flex items-center gap-2 rounded-lg border bg-background px-3 py-2">
              <input
                type="checkbox"
                checked={modelForm.tools}
                onChange={(event) =>
                  setModelForm((current) => ({ ...current, tools: event.target.checked }))
                }
                className="size-4 rounded border"
              />
              <span className="text-sm text-foreground">Enable tools</span>
            </label>

            {modelError ? (
              <p className="text-xs text-destructive">{modelError}</p>
            ) : null}
          </div>

          <DialogActions>
            <Button type="button" variant="outline" onClick={resetModelDialog}>
              Cancel
            </Button>
            <Button
              type="button"
              disabled={isSubmitting || !hasProviders}
              onClick={() => void handleModelSubmit()}
            >
              Save model
            </Button>
          </DialogActions>
        </DialogContent>
      </Dialog>
    </>
  );
}
