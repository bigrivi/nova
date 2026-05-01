import type {
  NovaMessageRecord,
  NovaModelCreateRequest,
  NovaModelRecord,
  NovaProviderCreateRequest,
  NovaProviderRecord,
  NovaSessionSummary,
  NovaStreamEvent,
} from '../types/nova'

type JsonResponse<T> = {
  items: T[]
}

type StreamChatOptions = {
  message: string
  sessionId?: string | null
  provider?: string | null
  model?: string | null
  onEvent: (event: NovaStreamEvent) => void
}

const API_BASE = (import.meta.env.VITE_NOVA_API_BASE_URL || '').replace(/\/$/, '')

function buildUrl(path: string) {
  return `${API_BASE}${path}`
}

async function parseErrorMessage(response: Response): Promise<string> {
  const raw = await response.text()
  if (!raw) {
    return `Request failed with status ${response.status}`
  }

  try {
    const payload = JSON.parse(raw) as { detail?: string; message?: string }
    return payload.detail || payload.message || raw
  } catch {
    return raw
  }
}

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(await parseErrorMessage(response))
  }
  return (await response.json()) as T
}

export async function listModels(): Promise<NovaModelRecord[]> {
  const payload = await parseJson<JsonResponse<NovaModelRecord>>(
    await fetch(buildUrl('/api/models')),
  )
  return payload.items
}

export async function listProviders(): Promise<NovaProviderRecord[]> {
  const payload = await parseJson<JsonResponse<NovaProviderRecord>>(
    await fetch(buildUrl('/api/providers')),
  )
  return payload.items
}

export async function createProvider(
  payload: NovaProviderCreateRequest,
): Promise<NovaModelRecord[]> {
  const response = await parseJson<JsonResponse<NovaModelRecord>>(
    await fetch(buildUrl('/api/config/providers'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    }),
  )
  return response.items
}

export async function createModel(
  payload: NovaModelCreateRequest,
): Promise<NovaModelRecord[]> {
  const response = await parseJson<JsonResponse<NovaModelRecord>>(
    await fetch(buildUrl('/api/config/models'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    }),
  )
  return response.items
}

export async function listSessions(): Promise<NovaSessionSummary[]> {
  const payload = await parseJson<JsonResponse<NovaSessionSummary>>(
    await fetch(buildUrl('/api/sessions')),
  )
  return payload.items
}

export async function listMessages(sessionId: string): Promise<NovaMessageRecord[]> {
  const payload = await parseJson<JsonResponse<NovaMessageRecord>>(
    await fetch(buildUrl(`/api/sessions/${encodeURIComponent(sessionId)}/messages`)),
  )
  return payload.items
}

function emitFrame(frame: string, onEvent: (event: NovaStreamEvent) => void) {
  const payload = frame
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n')

  if (!payload || payload === '[DONE]') {
    return
  }

  onEvent(JSON.parse(payload) as NovaStreamEvent)
}

export async function streamChat(options: StreamChatOptions): Promise<void> {
  const response = await fetch(buildUrl('/api/chat/stream'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message: options.message,
      session_id: options.sessionId || undefined,
      provider: options.provider || undefined,
      model: options.model || undefined,
    }),
  })

  if (!response.ok) {
    throw new Error(await parseErrorMessage(response))
  }

  if (!response.body) {
    throw new Error('Stream response did not include a body.')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })

    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary).trim()
      buffer = buffer.slice(boundary + 2)
      if (frame) {
        emitFrame(frame, options.onEvent)
      }
      boundary = buffer.indexOf('\n\n')
    }

    if (done) {
      const finalFrame = buffer.trim()
      if (finalFrame) {
        emitFrame(finalFrame, options.onEvent)
      }
      return
    }
  }
}
