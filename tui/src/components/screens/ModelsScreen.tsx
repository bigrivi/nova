/** Models 屏幕：浏览/切换模型（持久化到 agent 配置） */
import { useEffect, useState } from 'react'
import type { NovaModelRecord } from '../../api/types.ts'
import { listModels, updateAgent } from '../../api/nova-api.ts'
import { useChatStore } from '../../stores/chat-store.ts'
import { useScreenStore } from '../../stores/screen-store.ts'
import { SearchableList } from './SearchableList.tsx'

export function ModelsScreen() {
  const [models, setModels] = useState<NovaModelRecord[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    void listModels()
      .then(setModels)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  async function handleSelect(model: NovaModelRecord): Promise<void> {
    useScreenStore.getState().close()
    useChatStore.setState({ provider: model.provider, model: model.model })
    try {
      await updateAgent('main', { provider: model.provider, model: model.model })
    } catch {
      // 持久化失败不阻塞本次切换
    }
  }

  return (
    <SearchableList
      title="Models"
      items={models}
      filter={(model, query) =>
        !query ||
        model.label.toLowerCase().includes(query.toLowerCase()) ||
        model.provider.includes(query) ||
        model.model.includes(query)
      }
      renderLabel={(model) => `${model.provider_name} / ${model.label}`}
      onSelect={(model) => void handleSelect(model)}
      onClose={() => useScreenStore.getState().close()}
      emptyText={error || 'no models configured'}
    />
  )
}
