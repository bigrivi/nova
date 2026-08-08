/** 历史消息转换：NovaMessageRecord → TuiMessage（简化版：text/reasoning/tool-call 还原，工具结果附加到对应调用） */
import type { NovaMessageRecord } from '../api/types.ts'
import type { MessagePart, TuiMessage } from '../stores/chat-store.ts'

function parseToolArgs(argumentsValue: unknown): string {
  if (typeof argumentsValue === 'string') return argumentsValue
  try {
    return JSON.stringify(argumentsValue, null, 2)
  } catch {
    return String(argumentsValue)
  }
}

export function recordToMessage(record: NovaMessageRecord): TuiMessage {
  if (record.role === 'user') {
    return {
      id: record.id,
      role: 'user',
      parts: [{ type: 'text', text: record.content }],
      status: 'done',
    }
  }
  const parts: MessagePart[] = []
  if (record.reasoning_content) {
    parts.push({
      type: 'reasoning',
      text: record.reasoning_content,
      elapsedMs: record.reasoning_elapsed_ms ?? null,
      completed: true,
    })
  }
  if (record.content) {
    parts.push({ type: 'text', text: record.content })
  }
  for (const tc of record.tool_calls) {
    const call = tc as {
      id?: string
      name?: string
      arguments?: unknown
    }
    parts.push({
      type: 'tool-call',
      toolCallId: call.id ?? '',
      toolName: call.name ?? 'unknown',
      argsText: parseToolArgs(call.arguments),
      outputText: '',
      status: 'done',
    })
  }
  return { id: record.id, role: 'assistant', parts, status: 'done' }
}

export function recordsToMessages(records: NovaMessageRecord[]): TuiMessage[] {
  const messages: TuiMessage[] = []
  const toolOutputById = new Map<string, string>()
  for (const record of records) {
    if (record.role === 'tool' && record.tool_call_id) {
      toolOutputById.set(record.tool_call_id, record.content)
    }
  }
  for (const record of records) {
    const message = recordToMessage(record)
    if (record.role === 'assistant') {
      const withOutput = message.parts.map((part) => {
        if (part.type === 'tool-call') {
          const output = toolOutputById.get(part.toolCallId)
          return output !== undefined ? { ...part, outputText: output } : part
        }
        return part
      })
      messages.push({ ...message, parts: withOutput })
    } else {
      messages.push(message)
    }
  }
  return messages
}
