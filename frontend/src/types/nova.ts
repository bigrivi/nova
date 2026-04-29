export type NovaSessionSummary = {
  id: string
  title: string | null
  updated_at: number
}

export type NovaMessageRecord = {
  id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  tool_call_id: string | null
  tool_calls: Array<Record<string, unknown>>
  time_created: number
}

export type NovaModelRecord = {
  id: string
  provider: string
  provider_name: string
  model: string
  label: string
  tools: boolean
}

export type NovaThreadSummary = {
  id: string
  title: string
  status: 'regular'
}

export type NovaStreamEvent = {
  type: string
  data?: Record<string, unknown>
  delta?: string
  errorText?: string
}
