import {
  AssistantRuntimeProvider,
  type ThreadMessageLike,
  useExternalStoreRuntime,
} from '@assistant-ui/react'
import {
  ArrowUpIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  LoaderCircleIcon,
} from 'lucide-react'
import { startTransition, useEffect, useRef, useState } from 'react'

import { ModelSelector } from '../components/assistant-ui/model-selector'
import { Thread } from '../components/assistant-ui/thread'
import { ThreadList } from '../components/assistant-ui/thread-list'
import { Button } from '../components/ui/button'
import { TooltipProvider } from '../components/ui/tooltip'
import { listMessages, listModels, listSessions, streamChat } from '../lib/nova-api'
import type {
  NovaModelRecord,
  NovaSessionSummary,
  NovaThreadSummary,
} from '../types/nova'

const DRAFT_THREAD_ID = '__draft__'

function createTextMessage(
  role: 'user' | 'assistant',
  text: string,
  id?: string,
): ThreadMessageLike {
  return {
    id: id ?? crypto.randomUUID(),
    role,
    content: text,
    createdAt: new Date(),
  }
}

function createWelcomeMessage(): ThreadMessageLike {
  return createTextMessage(
    'assistant',
    'Nova desktop preview is ready. Pick a model, start a new thread, or reopen a previous session from the left sidebar.',
    'welcome',
  )
}

function toThreadTitle(session: NovaSessionSummary) {
  return (session.title || 'Untitled session').trim() || 'Untitled session'
}

function toThreadSummary(session: NovaSessionSummary): NovaThreadSummary {
  return {
    id: session.id,
    title: toThreadTitle(session),
    status: 'regular',
  }
}

function toThreadMessages(
  messages: Array<{ id: string; role: 'user' | 'assistant'; content: string }>,
): ThreadMessageLike[] {
  return messages.map((message) =>
    createTextMessage(message.role, message.content, message.id),
  )
}

function upsertThread(
  threads: NovaThreadSummary[],
  nextThread: NovaThreadSummary,
): NovaThreadSummary[] {
  const filtered = threads.filter((thread) => thread.id !== nextThread.id)
  return [nextThread, ...filtered]
}

function buildDraftMessages(previous: ThreadMessageLike[]) {
  if (
    previous.length === 1 &&
    previous[0]?.id === 'welcome' &&
    previous[0]?.role === 'assistant'
  ) {
    return []
  }
  return previous
}

function setAssistantText(
  messages: ThreadMessageLike[],
  assistantMessageId: string,
  updater: (text: string) => string,
) {
  return messages.map((message) => {
    if (message.id !== assistantMessageId || message.role !== 'assistant') {
      return message
    }

    const currentText = typeof message.content === 'string' ? message.content : ''
    return {
      ...message,
      content: updater(currentText),
    }
  })
}

export function NovaAppShell() {
  const [threads, setThreads] = useState<NovaThreadSummary[]>([])
  const [messagesByThreadId, setMessagesByThreadId] = useState<
    Record<string, ThreadMessageLike[]>
  >({
    [DRAFT_THREAD_ID]: [createWelcomeMessage()],
  })
  const [currentThreadId, setCurrentThreadId] = useState(DRAFT_THREAD_ID)
  const [models, setModels] = useState<NovaModelRecord[]>([])
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [statusText, setStatusText] = useState('Ready')
  const [statusError, setStatusError] = useState<string | null>(null)
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [composerText, setComposerText] = useState('')
  const composerRef = useRef<HTMLTextAreaElement | null>(null)

  const currentMessages = messagesByThreadId[currentThreadId] || []
  const activeThreadListId = threads.some((thread) => thread.id === currentThreadId)
    ? currentThreadId
    : undefined

  useEffect(() => {
    let cancelled = false

    async function bootstrap() {
      try {
        const [availableModels, savedSessions] = await Promise.all([
          listModels(),
          listSessions(),
        ])

        if (cancelled) {
          return
        }

        startTransition(() => {
          setModels(availableModels)
          setThreads(savedSessions.map(toThreadSummary))
          if (availableModels.length > 0) {
            setSelectedModelId((current) => current || availableModels[0].id)
          }
        })
      } catch (error) {
        if (!cancelled) {
          setStatusError(error instanceof Error ? error.message : String(error))
        }
      }
    }

    void bootstrap()

    return () => {
      cancelled = true
    }
  }, [])

  async function refreshSessions() {
    const savedSessions = await listSessions()
    startTransition(() => {
      setThreads(savedSessions.map(toThreadSummary))
    })
  }

  async function loadThread(threadId: string) {
    try {
      setStatusText('Loading session history...')
      setStatusError(null)

      const messages = await listMessages(threadId)
      startTransition(() => {
        setCurrentThreadId(threadId)
        setMessagesByThreadId((previous) => ({
          ...previous,
          [threadId]: toThreadMessages(messages),
        }))
      })
      setStatusText('Ready')
    } catch (error) {
      const messageText = error instanceof Error ? error.message : String(error)
      setStatusError(messageText)
      setStatusText('History failed')
      throw error
    }
  }

  function setThreadMessages(
    threadId: string,
    updater:
      | ThreadMessageLike[]
      | ((messages: ThreadMessageLike[]) => ThreadMessageLike[]),
  ) {
    setMessagesByThreadId((previous) => {
      const current = previous[threadId] || []
      return {
        ...previous,
        [threadId]: typeof updater === 'function' ? updater(current) : updater,
      }
    })
  }

  function switchToDraftThread() {
    if (isRunning) {
      return
    }

    startTransition(() => {
      setCurrentThreadId(DRAFT_THREAD_ID)
      setMessagesByThreadId((previous) => ({
        ...previous,
        [DRAFT_THREAD_ID]: previous[DRAFT_THREAD_ID] || [createWelcomeMessage()],
      }))
    })
    setStatusText('Ready')
    setStatusError(null)
    setComposerText('')
  }

  useEffect(() => {
    const textarea = composerRef.current
    if (!textarea) {
      return
    }

    textarea.style.height = '0px'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`
  }, [composerText])

  useEffect(() => {
    if (isRunning) {
      return
    }

    const textarea = composerRef.current
    if (!textarea) {
      return
    }

    textarea.focus({ preventScroll: true })
    const caret = textarea.value.length
    textarea.setSelectionRange(caret, caret)
  }, [currentThreadId, isRunning])

  async function submitPrompt(prompt: string) {
    if (!prompt) {
      return
    }

    const selectedModel = models.find((item) => item.id === selectedModelId) || null
    const originThreadId = currentThreadId
    const userMessageId = crypto.randomUUID()
    const assistantMessageId = crypto.randomUUID()
    const userMessage = createTextMessage('user', prompt, userMessageId)
    const assistantMessage = createTextMessage('assistant', '', assistantMessageId)
    let activeThreadId = originThreadId

    setIsRunning(true)
    setStatusText('Streaming response...')
    setStatusError(null)
    setComposerText('')

    setThreadMessages(originThreadId, (previous) => [
      ...buildDraftMessages(previous),
      userMessage,
      assistantMessage,
    ])

    try {
      await streamChat({
        message: prompt,
        sessionId: originThreadId === DRAFT_THREAD_ID ? null : originThreadId,
        provider: selectedModel?.provider || null,
        model: selectedModel?.model || null,
        onEvent: (event) => {
          if (event.type === 'data-nova-session') {
            const sessionId = String(event.data?.sessionId || '')
            if (!sessionId) {
              return
            }

            activeThreadId = sessionId
            startTransition(() => {
              setMessagesByThreadId((previous) => {
                const sourceMessages = previous[originThreadId] || []
                return {
                  ...previous,
                  [sessionId]: sourceMessages,
                  [DRAFT_THREAD_ID]:
                    originThreadId === DRAFT_THREAD_ID
                      ? [createWelcomeMessage()]
                      : previous[DRAFT_THREAD_ID] || [createWelcomeMessage()],
                }
              })
              setCurrentThreadId(sessionId)
              setThreads((previous) =>
                upsertThread(previous, {
                  id: sessionId,
                  title: prompt.slice(0, 64) || 'Untitled session',
                  status: 'regular',
                }),
              )
            })
            return
          }

          if (event.type === 'text-delta') {
            setThreadMessages(activeThreadId, (previous) =>
              setAssistantText(previous, assistantMessageId, (text) => text + (event.delta || '')),
            )
            return
          }

          if (event.type === 'data-nova-input-required') {
            const messageText = String(event.data?.message || 'User input required')
            setThreadMessages(activeThreadId, (previous) =>
              setAssistantText(
                previous,
                assistantMessageId,
                (text) => `${text}\n\n${messageText}`.trim(),
              ),
            )
            return
          }

          if (event.type === 'error') {
            throw new Error(event.errorText || 'Unknown error')
          }
        },
      })

      if (activeThreadId !== DRAFT_THREAD_ID) {
        await Promise.all([loadThread(activeThreadId), refreshSessions()])
      } else {
        setStatusText('Ready')
      }
    } catch (error) {
      const messageText = error instanceof Error ? error.message : String(error)
      setStatusError(messageText)
      setStatusText('Request failed')
      setThreadMessages(activeThreadId, (previous) =>
        setAssistantText(previous, assistantMessageId, () => `[error] ${messageText}`),
      )
    } finally {
      setIsRunning(false)
    }
  }

  async function handleComposerSubmit() {
    const prompt = composerText.trim()
    if (!prompt || isRunning) {
      return
    }

    await submitPrompt(prompt)
  }

  const runtime = useExternalStoreRuntime({
    messages: currentMessages,
    isRunning,
    onNew: async () => {},
    convertMessage: (message) => message,
    setMessages: (messages) => {
      setThreadMessages(currentThreadId, [...messages])
    },
    adapters: {
      threadList: {
        threadId: activeThreadListId,
        threads,
        archivedThreads: [],
        onSwitchToNewThread: switchToDraftThread,
        onSwitchToThread: (threadId) => {
          if (isRunning || threadId === currentThreadId) {
            return
          }
          void loadThread(threadId)
        },
      },
    },
  })

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <div className="flex h-full min-h-0 bg-muted/30 text-foreground">
          <aside
            className={`flex h-full shrink-0 flex-col overflow-hidden bg-sidebar/80 backdrop-blur transition-[width,opacity] duration-200 ease-out ${
              isSidebarCollapsed ? 'w-0 opacity-0' : 'w-[280px] border-r opacity-100'
            }`}
          >
            {!isSidebarCollapsed && (
              <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
                <ThreadList />
              </div>
            )}
          </aside>

          <main
            className="relative flex min-h-0 min-w-0 flex-1 flex-col bg-background"
            style={{ ['--thread-max-width' as string]: '44rem' }}
          >
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="absolute left-4 top-4 z-20 rounded-full bg-background/90 shadow-sm backdrop-blur"
              aria-label={
                isSidebarCollapsed ? 'Expand thread list sidebar' : 'Collapse thread list sidebar'
              }
              onClick={() => setIsSidebarCollapsed((value) => !value)}
            >
              {isSidebarCollapsed ? (
                <ChevronRightIcon className="size-4" />
              ) : (
                <ChevronLeftIcon className="size-4" />
              )}
            </Button>

            <div className="min-h-0 flex-1 overflow-hidden pt-2">
              <Thread />
            </div>

            <div className="shrink-0 pb-4">
              <div className="mx-auto w-full max-w-(--thread-max-width) px-4">
                <div className="rounded-[24px] border bg-background p-3 shadow-sm transition-shadow focus-within:border-ring/75 focus-within:ring-2 focus-within:ring-ring/20">
                  <textarea
                    ref={composerRef}
                    value={composerText}
                    rows={1}
                    disabled={isRunning}
                    placeholder="Send a message..."
                    aria-label="Message input"
                    className="max-h-40 min-h-10 w-full resize-none bg-transparent px-1 py-1 text-sm outline-none placeholder:text-muted-foreground/80 disabled:cursor-not-allowed"
                    onChange={(event) => setComposerText(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' && !event.shiftKey) {
                        event.preventDefault()
                        void handleComposerSubmit()
                      }
                    }}
                  />

                  <div className="mt-3 flex items-center justify-between gap-3">
                    <div
                      className={`text-xs ${
                        statusError ? 'text-destructive' : 'text-muted-foreground'
                      }`}
                    >
                      {statusError || statusText}
                    </div>

                    <div className="flex items-center gap-2">
                      <ModelSelector
                        compact
                        models={models}
                        selectedModelId={selectedModelId}
                        onSelect={setSelectedModelId}
                      />

                      <Button
                        type="button"
                        size="icon"
                        className="rounded-full"
                        disabled={isRunning || composerText.trim().length === 0}
                        onClick={() => {
                          void handleComposerSubmit()
                        }}
                      >
                        {isRunning ? (
                          <LoaderCircleIcon className="size-4 animate-spin" />
                        ) : (
                          <ArrowUpIcon className="size-4" />
                        )}
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </main>
        </div>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  )
}
