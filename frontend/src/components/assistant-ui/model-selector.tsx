import type { NovaModelRecord } from '../../types/nova'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from '../ui/select'

type ModelSelectorProps = {
  models: NovaModelRecord[]
  selectedModelId: string | null
  onSelect: (modelId: string) => void
  compact?: boolean
}

type ModelGroup = {
  provider: string
  providerName: string
  models: NovaModelRecord[]
}

function groupModels(models: NovaModelRecord[]): ModelGroup[] {
  const groups = new Map<string, ModelGroup>()

  for (const model of models) {
    const existing = groups.get(model.provider)
    if (existing) {
      existing.models.push(model)
      continue
    }

    groups.set(model.provider, {
      provider: model.provider,
      providerName: model.provider_name,
      models: [model],
    })
  }

  return [...groups.values()]
}

function renderGroupedItems(groups: ModelGroup[]) {
  return groups.flatMap((group, index) => {
    const parts = [
      <SelectGroup key={group.provider}>
        <SelectLabel className="px-2.5 pt-2 pb-1 font-semibold text-[10px] uppercase tracking-[0.14em] text-foreground/65">
          {group.providerName}
        </SelectLabel>
        {group.models.map((model) => (
          <SelectItem
            key={model.id}
            value={model.id}
            className="pl-5"
          >
            <span className="inline-block pl-1">{model.label}</span>
          </SelectItem>
        ))}
      </SelectGroup>,
    ]

    if (index < groups.length - 1) {
      parts.push(
        <SelectSeparator
          key={`${group.provider}-separator`}
          className="my-1.5"
        />,
      )
    }

    return parts
  })
}

export function ModelSelector({
  models,
  selectedModelId,
  onSelect,
  compact = false,
}: ModelSelectorProps) {
  const hasModels = models.length > 0
  const selectId = compact ? 'nova-model-select-inline' : 'nova-model-select'
  const groupedModels = groupModels(models)
  const selectedModel =
    models.find((model) => model.id === selectedModelId) ?? models[0] ?? null
  const selectedValue = selectedModel?.id

  if (compact) {
    return (
      <div>
        <label className="sr-only" htmlFor={selectId}>
          Active model
        </label>
        <Select
          value={selectedValue}
          onValueChange={onSelect}
          disabled={!hasModels}
        >
          <SelectTrigger
            id={selectId}
            aria-label="Active model"
            title={selectedModel?.label || 'No models available'}
            className="h-8 w-32 rounded-full border-border/60 bg-background/85 px-2.5 py-0 text-[11px] font-medium text-muted-foreground shadow-none hover:bg-muted/35 focus:bg-background focus:text-foreground focus-visible:ring-ring/15 sm:w-36"
          >
            <SelectValue placeholder="No models available" />
          </SelectTrigger>
          <SelectContent align="end">
            {renderGroupedItems(groupedModels)}
          </SelectContent>
        </Select>
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

      <div>
        <Select
          value={selectedValue}
          onValueChange={onSelect}
          disabled={!hasModels}
        >
          <SelectTrigger
            id={selectId}
            aria-label="Active model"
            className="h-10 w-full rounded-xl"
          >
            <SelectValue placeholder="No models available" />
          </SelectTrigger>
          <SelectContent>
            {renderGroupedItems(groupedModels)}
          </SelectContent>
        </Select>
      </div>
    </div>
  )
}
