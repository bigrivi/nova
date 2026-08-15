/** Sessions 屏幕：浏览/加载持久会话 */
import { useEffect, useState } from 'react'
import { listMessages, listSessions } from '../../api/nova-api.ts'
import type { NovaSessionSummary } from '../../api/types.ts'
import { useChatStore } from '../../stores/chat-store.ts'
import { useScreenStore } from '../../stores/screen-store.ts'
import { recordsToMessages } from '../../utils/history.ts'
import { SearchableList } from './SearchableList.tsx'

function formatTime(ms: number): string {
  const diff = Date.now() - ms
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(ms).toLocaleDateString()
}

export function SessionsScreen() {
  const [sessions, setSessions] = useState<NovaSessionSummary[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    void listSessions()
      .then(setSessions)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
  }, [])

  async function handleSelect(session: NovaSessionSummary): Promise<void> {
    useScreenStore.getState().close()
    try {
      const records = await listMessages(session.id)
      const messages = recordsToMessages(records)
      useChatStore.getState().loadHistory(session.id, messages)
    } catch (err) {
      useChatStore.getState().failStream(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <SearchableList
      title="Sessions"
      items={sessions}
      filter={(session, query) =>
        !query ||
        (session.title ?? '').toLowerCase().includes(query.toLowerCase())
      }
      onSelect={(session) => void handleSelect(session)}
      onClose={() => useScreenStore.getState().close()}
      renderLabel={(session) =>
        `${session.title ?? '(untitled)'}  —  ${formatTime(session.updated_at)}`
      }
      emptyText={error || 'no sessions yet'}
    />
  )
}
