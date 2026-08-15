/** 聊天全局状态：消息（parts 结构）、会话 ID、流式状态（zustand） */
import { create } from 'zustand'

export type TextPart = { type: 'text'; text: string }
export type ReasoningPart = {
  type: 'reasoning'
  text: string
  elapsedMs: number | null
  completed: boolean
}
export type ToolCallPart = {
  type: 'tool-call'
  toolCallId: string
  toolName: string
  argsText: string
  /** 原始参数对象，供摘要提取；无结构化参数的工具（如 ask_user）为 null */
  args: Record<string, unknown> | null
  outputText: string
  status: 'running' | 'done' | 'error'
  error?: string
}
export type MessagePart = TextPart | ReasoningPart | ToolCallPart

export type TuiMessage = {
  id: string
  role: 'user' | 'assistant'
  parts: MessagePart[]
  status: 'streaming' | 'done' | 'error'
  error?: string
}

/** 本轮对话的模型选择（P3 由模型选择屏幕接管） */
export const DEFAULT_PROVIDER = 'opencode'
export const DEFAULT_MODEL = 'deepseek-v4-flash-free'

type ChatState = {
  messages: TuiMessage[]
  sessionId: string | null
  isStreaming: boolean
  provider: string
  model: string

  setSessionId: (sessionId: string) => void
  addUserMessage: (text: string) => void
  startAssistantMessage: () => string
  startTextPart: (messageId: string) => void
  appendTextDelta: (messageId: string, delta: string) => void
  startReasoningPart: (messageId: string) => void
  appendReasoningDelta: (messageId: string, delta: string) => void
  endReasoningPart: (messageId: string, elapsedMs: number | null) => void
  startToolCall: (
    messageId: string,
    tool: { toolCallId: string; toolName: string },
  ) => void
  setToolInput: (messageId: string, toolCallId: string, input: unknown) => void
  setToolOutput: (
    messageId: string,
    toolCallId: string,
    output: unknown,
  ) => void
  failToolCall: (
    messageId: string,
    toolCallId: string,
    message: string,
  ) => void
  completeStream: () => void
  failStream: (error: string) => void
  loadHistory: (sessionId: string, messages: TuiMessage[]) => void
  reset: () => void
}

function makeId(): string {
  return `msg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

function patchMessage(
  messages: TuiMessage[],
  messageId: string,
  patch: (msg: TuiMessage) => TuiMessage,
): TuiMessage[] {
  return messages.map((msg) => (msg.id === messageId ? patch(msg) : msg))
}

function lastPartOfType<T extends MessagePart['type']>(
  parts: MessagePart[],
  type: T,
): (MessagePart & { type: T }) | null {
  for (let i = parts.length - 1; i >= 0; i--) {
    if (parts[i]?.type === type) {
      return parts[i] as MessagePart & { type: T }
    }
  }
  return null
}

/** tool 输出/参数的展示文本（对象 → 递归解包 content 字段；否则紧凑 JSON） */
function toDisplayText(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'object') {
    const content = (value as Record<string, unknown>).content
    if (content !== undefined) {
      return toDisplayText(content)
    }
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/** 提取工具参数为普通对象，供摘要展示；非对象（如数组/字符串）返回 null */
function toArgsObject(value: unknown): Record<string, unknown> | null {
  if (value == null || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  return value as Record<string, unknown>
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  sessionId: null,
  isStreaming: false,
  provider: DEFAULT_PROVIDER,
  model: DEFAULT_MODEL,

  setSessionId: (sessionId) => set({ sessionId }),

  addUserMessage: (text) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: makeId(),
          role: 'user',
          parts: [{ type: 'text', text }],
          status: 'done',
        },
      ],
    })),

  startAssistantMessage: () => {
    const id = makeId()
    set((state) => ({
      isStreaming: true,
      messages: [
        ...state.messages,
        { id, role: 'assistant', parts: [], status: 'streaming' },
      ],
    }))
    return id
  },

  startTextPart: (messageId) =>
    set((state) => ({
      messages: patchMessage(state.messages, messageId, (msg) => {
        if (msg.parts.length === 0 || !lastPartOfType(msg.parts, 'text')) {
          return { ...msg, parts: [...msg.parts, { type: 'text', text: '' }] }
        }
        return msg
      }),
    })),

  appendTextDelta: (messageId, delta) =>
    set((state) => ({
      messages: patchMessage(state.messages, messageId, (msg) => {
        const existing = lastPartOfType(msg.parts, 'text')
        if (existing) {
          return {
            ...msg,
            parts: msg.parts.map((part, i) =>
              i === msg.parts.length - 1 && part.type === 'text'
                ? { ...part, text: part.text + delta }
                : part,
            ),
          }
        }
        return { ...msg, parts: [...msg.parts, { type: 'text', text: delta }] }
      }),
    })),

  startReasoningPart: (messageId) =>
    set((state) => ({
      messages: patchMessage(state.messages, messageId, (msg) => {
        if (lastPartOfType(msg.parts, 'reasoning')) {
          return msg
        }
        return {
          ...msg,
          parts: [
            ...msg.parts,
            { type: 'reasoning', text: '', elapsedMs: null, completed: false },
          ],
        }
      }),
    })),

  appendReasoningDelta: (messageId, delta) =>
    set((state) => ({
      messages: patchMessage(state.messages, messageId, (msg) => {
        const reasoning = lastPartOfType(msg.parts, 'reasoning')
        if (!reasoning) {
          return {
            ...msg,
            parts: [
              ...msg.parts,
              { type: 'reasoning', text: delta, elapsedMs: null, completed: false },
            ],
          }
        }
        return {
          ...msg,
          parts: msg.parts.map((part) =>
            part.type === 'reasoning'
              ? { ...part, text: part.text + delta }
              : part,
          ),
        }
      }),
    })),

  endReasoningPart: (messageId, elapsedMs) =>
    set((state) => ({
      messages: patchMessage(state.messages, messageId, (msg) => ({
        ...msg,
        parts: msg.parts.map((part) =>
          part.type === 'reasoning'
            ? { ...part, completed: true, elapsedMs }
            : part,
        ),
      })),
    })),

  startToolCall: (messageId, tool) =>
    set((state) => ({
      messages: patchMessage(state.messages, messageId, (msg) => ({
        ...msg,
        parts: [
          ...msg.parts,
          {
            type: 'tool-call',
            toolCallId: tool.toolCallId,
            toolName: tool.toolName,
            argsText: '',
            args: null,
            outputText: '',
            status: 'running',
          },
        ],
      })),
    })),

  setToolInput: (messageId, toolCallId, input) =>
    set((state) => ({
      messages: patchMessage(state.messages, messageId, (msg) => ({
        ...msg,
        parts: msg.parts.map((part) =>
          part.type === 'tool-call' && part.toolCallId === toolCallId
            ? { ...part, argsText: toDisplayText(input), args: toArgsObject(input) }
            : part,
        ),
      })),
    })),

  setToolOutput: (messageId, toolCallId, output) =>
    set((state) => ({
      messages: patchMessage(state.messages, messageId, (msg) => ({
        ...msg,
        parts: msg.parts.map((part) =>
          part.type === 'tool-call' && part.toolCallId === toolCallId
            ? { ...part, outputText: toDisplayText(output), status: 'done' }
            : part,
        ),
      })),
    })),

  failToolCall: (messageId, toolCallId, message) =>
    set((state) => ({
      messages: patchMessage(state.messages, messageId, (msg) => ({
        ...msg,
        parts: msg.parts.map((part) =>
          part.type === 'tool-call' && part.toolCallId === toolCallId
            ? { ...part, status: 'error', error: message }
            : part,
        ),
      })),
    })),

  completeStream: () =>
    set((state) => ({
      isStreaming: false,
      messages: state.messages.map((msg) =>
        msg.status === 'streaming' ? { ...msg, status: 'done' } : msg,
      ),
    })),

  failStream: (error) =>
    set((state) => ({
      isStreaming: false,
      messages: state.messages.map((msg) =>
        msg.status === 'streaming' ? { ...msg, status: 'error', error } : msg,
      ),
    })),

  loadHistory: (sessionId, messages) =>
    set({ sessionId, messages, isStreaming: false }),

  reset: () => set({ messages: [], sessionId: null, isStreaming: false }),
}))

/** 供 stream 逻辑读取最新 state（避免闭包捕获过期值） */
export const getChatState = () => useChatStore.getState()
