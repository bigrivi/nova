import type { ThreadMessageLike } from '@assistant-ui/react'

import type { NovaJsonObject, NovaMessageRecord } from '../types/nova'

type AssistantPart = Exclude<ThreadMessageLike['content'], string>[number]

type ToolCallLike = {
  id: string
  name: string
  arguments: string
}

function createTextMessage(
  role: 'user' | 'assistant',
  text: string,
  id: string,
  createdAt: number,
): ThreadMessageLike {
  return {
    id,
    role,
    content: text,
    createdAt: new Date(createdAt),
  }
}

function parseToolCallLike(value: unknown): ToolCallLike | null {
  if (!value || typeof value !== 'object') {
    return null
  }

  const raw = value as Record<string, unknown>
  const id = String(raw.id ?? '').trim()
  const name = String(raw.name ?? '').trim()
  const argumentsText = String(raw.arguments ?? '').trim()
  if (!name) {
    return null
  }

  return {
    id: id || crypto.randomUUID(),
    name,
    arguments: argumentsText,
  }
}

function parseJsonObject(value: string): NovaJsonObject {
  const text = value.trim()
  if (!text) {
    return {}
  }

  try {
    const parsed = JSON.parse(text)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as NovaJsonObject)
      : {}
  } catch {
    return {}
  }
}

function parseToolResultContent(content: string): unknown {
  const text = content.trim()
  if (!text) {
    return {}
  }

  try {
    return JSON.parse(text)
  } catch {
    return { content }
  }
}

export function toThreadMessages(messages: NovaMessageRecord[]): ThreadMessageLike[] {
  const threadMessages: ThreadMessageLike[] = []
  const toolPartIndexByCallId = new Map<
    string,
    {
      messageIndex: number
      partIndex: number
    }
  >()

  for (const message of messages) {
    if (message.role === 'user') {
      threadMessages.push(
        createTextMessage('user', message.content, message.id, message.time_created),
      )
      continue
    }

    if (message.role === 'assistant') {
      const content: AssistantPart[] = []
      if (message.content) {
        content.push({ type: 'text', text: message.content })
      }

      for (const toolCall of message.tool_calls) {
        const parsed = parseToolCallLike(toolCall)
        if (!parsed) {
          continue
        }

        content.push({
          type: 'tool-call',
          toolCallId: parsed.id,
          toolName: parsed.name,
          args: parseJsonObject(parsed.arguments),
          argsText: parsed.arguments,
        })
      }

      if (content.length === 0) {
        continue
      }

      const messageIndex = threadMessages.length
      const assistantMessage: ThreadMessageLike = {
        id: message.id,
        role: 'assistant',
        content,
        createdAt: new Date(message.time_created),
      }
      threadMessages.push(assistantMessage)

      content.forEach((part, partIndex) => {
        if (part.type !== 'tool-call' || !part.toolCallId) {
          return
        }
        toolPartIndexByCallId.set(part.toolCallId, {
          messageIndex,
          partIndex,
        })
      })
      continue
    }

    if (message.role !== 'tool') {
      continue
    }

    const toolCallId = String(message.tool_call_id ?? '').trim()
    if (!toolCallId) {
      continue
    }

    const target = toolPartIndexByCallId.get(toolCallId)
    if (!target) {
      continue
    }

    const assistantMessage = threadMessages[target.messageIndex]
    if (!assistantMessage || assistantMessage.role !== 'assistant' || typeof assistantMessage.content === 'string') {
      continue
    }

    const part = assistantMessage.content[target.partIndex]
    if (!part || part.type !== 'tool-call') {
      continue
    }

    const nextContent = [...assistantMessage.content]
    nextContent[target.partIndex] = {
      ...part,
      result: parseToolResultContent(message.content),
    }
    threadMessages[target.messageIndex] = {
      ...assistantMessage,
      content: nextContent,
    }
  }

  return threadMessages
}
