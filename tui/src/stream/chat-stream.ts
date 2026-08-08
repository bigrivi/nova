/** 聊天流处理状态机：SSE 事件 → store 更新（纯逻辑，无 UI 依赖）
 *
 * 事件协议参照 nova/server/ai_sdk_stream.py + frontend/src/app/NovaAppShell.tsx：
 * - data-nova-session       首次会话创建，记录 sessionId，后续消息复用
 * - text-* / reasoning-*    文本与推理流
 * - tool-input-* / tool-output-available / data-nova-tool-error  工具调用
 * - data-nova-approval-required  命令审批挂起 → approval store
 * - data-nova-input-required     ask_user 挂起 → 激活 ask-user 表单
 * - abort / finish / error  收尾
 */
import { streamChat } from '../api/nova-api.ts'
import { getChatState } from '../stores/chat-store.ts'
import {
  useAskUserStore,
  type AskQuestion,
} from '../stores/ask-user-store.ts'
import { useApprovalStore } from '../stores/approval-store.ts'

export type ChatRunOptions = {
  message: string
}

/** 解析 ask_user 工具的 input 为问题列表（兼容 {questions:[...]} 与 {question:{...}}） */
export function parseAskQuestions(input: unknown): AskQuestion[] {
  if (!input || typeof input !== 'object') return []
  const obj = input as Record<string, unknown>
  const raw = Array.isArray(obj.questions) ? obj.questions : obj.question
  const list = Array.isArray(raw) ? raw : raw != null ? [raw] : []
  const result: AskQuestion[] = []
  for (let i = 0; i < list.length; i++) {
    const q = list[i]
    if (!q || typeof q !== 'object') continue
    const qo = q as Record<string, unknown>
    const inputType = String(qo.input_type ?? 'text').toLowerCase()
    result.push({
      id: String(qo.id ?? `q${i}`),
      header: String(qo.header ?? ''),
      question: String(qo.question ?? ''),
      inputType:
        inputType === 'select'
          ? 'select'
          : inputType === 'confirm'
            ? 'confirm'
            : 'text',
      options: Array.isArray(qo.options)
        ? qo.options
            .filter((o): o is Record<string, unknown> => !!o && typeof o === 'object')
            .map((o) => ({
              label: String(o.label ?? o.value ?? ''),
              value: o.value !== undefined ? String(o.value) : undefined,
            }))
        : [],
      multiple: Boolean(qo.multiple),
      required: qo.required !== false,
    })
  }
  return result
}

/** 答案格式：与前端 handleSubmit 一致（Q/A 行，作为新消息提交） */
export function formatAskAnswers(
  questions: AskQuestion[],
  answers: Record<string, string>,
): string {
  const lines: string[] = []
  for (const q of questions) {
    lines.push(`Q (${q.id}): ${q.question}`)
    lines.push(`A: ${answers[q.id] ?? ''}`)
    lines.push('')
  }
  return lines.join('\n').trim()
}

/** 执行一轮对话：乐观插入消息 → 流式消费 → 收尾状态机。 */
export async function runChatStream(options: ChatRunOptions): Promise<void> {
  const store = getChatState()
  const { sessionId, provider, model } = store

  store.addUserMessage(options.message)
  const assistantId = store.startAssistantMessage()

  let pendingAskQuestions: AskQuestion[] | null = null

  try {
    await streamChat({
      message: options.message,
      sessionId,
      provider,
      model,
      onEvent: (event) => {
        const current = getChatState()
        switch (event.type) {
          case 'data-nova-session': {
            const next = String(event.data?.sessionId ?? '')
            if (next && next !== current.sessionId) {
              current.setSessionId(next)
            }
            return
          }
          case 'text-start': {
            current.startTextPart(assistantId)
            return
          }
          case 'text-delta': {
            current.appendTextDelta(assistantId, event.delta ?? '')
            return
          }
          case 'reasoning-start': {
            current.startReasoningPart(assistantId)
            return
          }
          case 'reasoning-delta': {
            current.appendReasoningDelta(assistantId, event.delta ?? '')
            return
          }
          case 'reasoning-end': {
            current.endReasoningPart(assistantId, event.elapsedMs ?? null)
            return
          }
          case 'tool-input-start': {
            current.startToolCall(assistantId, {
              toolCallId: event.toolCallId ?? '',
              toolName: event.toolName ?? 'unknown',
            })
            return
          }
          case 'tool-input-available': {
            current.setToolInput(assistantId, event.toolCallId ?? '', event.input)
            if (event.toolName === 'ask_user') {
              pendingAskQuestions = parseAskQuestions(event.input)
            }
            return
          }
          case 'tool-output-available': {
            current.setToolOutput(assistantId, event.toolCallId ?? '', event.output)
            return
          }
          case 'data-nova-tool-error': {
            current.failToolCall(
              assistantId,
              String(event.data?.toolCallId ?? ''),
              String(event.data?.message ?? 'Tool failed'),
            )
            return
          }
          case 'data-nova-approval-required': {
            useApprovalStore.getState().setPending({
              sessionId: String(event.data?.sessionId ?? current.sessionId ?? ''),
              requestId: String(event.data?.requestId ?? ''),
              command: String(event.data?.command ?? ''),
              description: String(event.data?.description ?? ''),
            })
            return
          }
          case 'data-nova-input-required': {
            if (pendingAskQuestions && pendingAskQuestions.length > 0) {
              useAskUserStore.getState().setActive(pendingAskQuestions)
            }
            // 服务端随后会发 finish + [DONE]，流自然结束；
            // 此处不同步 completeStream，避免在 SSE 回调中同步触发 React 更新
            return
          }
          case 'abort': {
            // 同上：等待流自然结束，收尾统一在 resolve 后进行
            return
          }
          case 'error': {
            throw new Error(event.errorText ?? 'Unknown stream error')
          }
          default:
            // data-nova-heartbeat / data-nova-compaction-* / start / finish
            return
        }
      },
    })
    getChatState().completeStream()
  } catch (err) {
    getChatState().failStream(err instanceof Error ? err.message : String(err))
  }
}
