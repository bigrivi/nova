import { ChevronDownIcon } from 'lucide-react'

import type { NovaModelRecord } from '../../types/nova'

type ModelSelectorProps = {
  models: NovaModelRecord[]
  selectedModelId: string | null
  onSelect: (modelId: string) => void
  compact?: boolean
}

export function ModelSelector({
  models,
  selectedModelId,
  onSelect,
  compact = false,
}: ModelSelectorProps) {
  const hasModels = models.length > 0
  const selectId = compact ? 'nova-model-select-inline' : 'nova-model-select'
  const selectedModel =
    models.find((model) => model.id === selectedModelId) ?? models[0] ?? null

  if (compact) {
    return (
      <div className="relative">
        <label className="sr-only" htmlFor={selectId}>
          Active model
        </label>
        <select
          id={selectId}
          title={selectedModel?.label || 'No models available'}
          className="h-8 w-32 appearance-none rounded-full border border-border/60 bg-background/85 px-2.5 pr-7 text-[11px] font-medium text-muted-foreground shadow-none outline-none transition-colors hover:bg-muted/35 focus:border-ring focus:bg-background focus:text-foreground focus:ring-2 focus:ring-ring/15 disabled:cursor-not-allowed disabled:opacity-50 sm:w-36"
          value={selectedModelId || ''}
          onChange={(event) => onSelect(event.target.value)}
          disabled={!hasModels}
        >
          {!hasModels && <option value="">No models available</option>}
          {models.map((model) => (
            <option key={model.id} value={model.id}>
              {model.label}
            </option>
          ))}
        </select>
        <ChevronDownIcon className="pointer-events-none absolute right-2 top-1/2 size-3 -translate-y-1/2 text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="space-y-3 rounded-2xl border bg-card p-4 shadow-sm">
      <div className="space-y-1">
        <label
          className="text-sm font-medium text-foreground"
          htmlFor={selectId}
        >
          Active model
        </label>
        <p className="text-xs leading-5 text-muted-foreground">
          The selected provider/model pair is sent as a per-request override to
          Nova&apos;s backend.
        </p>
      </div>

      <div className="relative">
        <select
          id={selectId}
          className="h-10 w-full appearance-none rounded-xl border bg-background px-3 pr-10 text-sm shadow-xs outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/20 disabled:cursor-not-allowed disabled:opacity-50"
          value={selectedModelId || ''}
          onChange={(event) => onSelect(event.target.value)}
          disabled={!hasModels}
        >
          {!hasModels && <option value="">No models available</option>}
          {models.map((model) => (
            <option key={model.id} value={model.id}>
              {model.provider_name} / {model.label}
            </option>
          ))}
        </select>
        <ChevronDownIcon className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
      </div>
    </div>
  )
}
