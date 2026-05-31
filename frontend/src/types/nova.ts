import type {
  ReadonlyJSONObject,
  ReadonlyJSONValue,
} from 'assistant-stream/utils'

export type NovaJsonObject = ReadonlyJSONObject
export type NovaJsonValue = ReadonlyJSONValue

export type NovaSessionSummary = {
  id: string
  title: string | null
  updated_at: number
  agent_key: string
}

export type NovaMessageRecord = {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  tool_call_id: string | null
  tool_calls: NovaJsonObject[]
  time_created: number
  images?: string[] | null
  reasoning_content?: string | null
  group_id?: string | null
}

export type NovaModelRecord = {
  id: string
  provider: string
  provider_name: string
  model: string
  label: string
  tools: boolean
}

export type NovaProviderRecord = {
  key: string
  name: string
  type: string
}

export type NovaProviderCreateRequest = {
  key: string
  type: string
  name: string
  base_url: string
  api_key: string
}

export type NovaModelCreateRequest = {
  provider: string
  model: string
  label: string
  tools: boolean
}

export type NovaThreadSummary = {
  id: string
  title: string
  status: 'regular'
}

export type NovaAttachmentContent = {
  type: string
  [key: string]: NovaJsonValue | undefined
}

export type NovaAttachmentData = {
  id: string
  type: string
  name: string
  contentType?: string
  content: NovaAttachmentContent[]
}

export type NovaStreamEvent = {
  type: string
  data?: NovaJsonObject
  delta?: string
  errorText?: string
  toolCallId?: string
  toolName?: string
  input?: NovaJsonObject
  output?: NovaJsonValue
}
