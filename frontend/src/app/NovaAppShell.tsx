import {
  AssistantRuntimeProvider,
  CompositeAttachmentAdapter,
  SimpleImageAttachmentAdapter,
  SimpleTextAttachmentAdapter,
  type ThreadMessageLike,
  useExternalStoreRuntime,
} from "@assistant-ui/react";
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  LanguagesIcon,
} from "lucide-react";
import { startTransition, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import i18n from "../i18n";

import { Thread } from "../components/assistant-ui/thread";
import { ThreadList } from "../components/assistant-ui/thread-list";
import { Button } from "../components/ui/button";
import { TooltipProvider } from "../components/ui/tooltip";
import { toThreadMessages } from "../lib/history-messages";
import {
  listMessages,
  listModels,
  listProviders,
  listSessions,
  streamChat,
} from "../lib/nova-api";
import type {
  NovaAttachmentData,
  NovaJsonObject,
  NovaModelRecord,
  NovaProviderRecord,
  NovaSessionSummary,
  NovaThreadSummary,
} from "../types/nova";

const DRAFT_THREAD_ID = "__draft__";

function createTextMessage(
  role: "user" | "assistant",
  text: string,
  id?: string,
): ThreadMessageLike {
  return {
    id: id ?? crypto.randomUUID(),
    role,
    content: text,
    createdAt: new Date(),
  };
}

function createAssistantMessage(id?: string): ThreadMessageLike {
  return {
    id: id ?? crypto.randomUUID(),
    role: "assistant",
    content: [],
    createdAt: new Date(),
  };
}

type AssistantPart = Exclude<ThreadMessageLike["content"], string>[number];

function createWelcomeMessage(): ThreadMessageLike {
  return createTextMessage(
    "assistant",
    i18n.t("app.welcomeMessage"),
    "welcome",
  );
}

function createOptimisticSessionTitle(userMessage: string): string {
  const title = userMessage.trim();
  if (!title) {
    return i18n.t("app.newSession");
  }

  if (title.length > 50) {
    return `${title.slice(0, 47)}...`;
  }

  return title;
}

function toThreadTitle(session: NovaSessionSummary) {
  const untitled = i18n.t("app.untitledSession");
  return (session.title || untitled).trim() || untitled;
}

function toThreadSummary(session: NovaSessionSummary): NovaThreadSummary {
  return {
    id: session.id,
    title: toThreadTitle(session),
    status: "regular",
  };
}

function upsertThread(
  threads: NovaThreadSummary[],
  nextThread: NovaThreadSummary,
): NovaThreadSummary[] {
  const filtered = threads.filter((thread) => thread.id !== nextThread.id);
  return [nextThread, ...filtered];
}

function buildDraftMessages(previous: ThreadMessageLike[]) {
  if (
    previous.length === 1 &&
    previous[0]?.id === "welcome" &&
    previous[0]?.role === "assistant"
  ) {
    return [];
  }
  return previous;
}

function setAssistantText(
  messages: ThreadMessageLike[],
  assistantMessageId: string,
  updater: (text: string) => string,
) {
  return messages.map((message) => {
    if (message.id !== assistantMessageId || message.role !== "assistant") {
      return message;
    }

    const parts =
      typeof message.content === "string"
        ? message.content
          ? [{ type: "text" as const, text: message.content }]
          : []
        : [...message.content];
    const textPartIndex = parts.findLastIndex((part) => part.type === "text");
    const currentText =
      textPartIndex >= 0 && parts[textPartIndex]?.type === "text"
        ? parts[textPartIndex].text
        : "";
    const nextText = updater(currentText);

    if (textPartIndex >= 0) {
      parts[textPartIndex] = { type: "text", text: nextText };
    } else if (nextText) {
      parts.push({ type: "text", text: nextText });
    }

    return {
      ...message,
      content: parts,
    };
  });
}

function upsertAssistantToolCall(
  messages: ThreadMessageLike[],
  assistantMessageId: string,
  payload: {
    toolCallId: string;
    toolName?: string;
    input?: NovaJsonObject;
    output?: unknown;
  },
) {
  return messages.map((message) => {
    if (message.id !== assistantMessageId || message.role !== "assistant") {
      return message;
    }

    const parts =
      typeof message.content === "string"
        ? message.content
          ? [{ type: "text" as const, text: message.content }]
          : []
        : [...message.content];
    const toolIndex = parts.findIndex(
      (part) =>
        part.type === "tool-call" && part.toolCallId === payload.toolCallId,
    );

    const current =
      toolIndex >= 0 && parts[toolIndex]?.type === "tool-call"
        ? parts[toolIndex]
        : null;

    const nextPart: AssistantPart = {
      type: "tool-call",
      toolCallId: payload.toolCallId,
      toolName: payload.toolName || current?.toolName || "tool",
      args: payload.input ?? current?.args ?? {},
      argsText:
        payload.input !== undefined
          ? JSON.stringify(payload.input)
          : (current?.argsText ?? ""),
      ...(payload.output !== undefined
        ? { result: payload.output }
        : current?.result !== undefined
          ? { result: current.result }
          : {}),
      ...(current?.isError !== undefined ? { isError: current.isError } : {}),
    };

    if (toolIndex >= 0) {
      parts[toolIndex] = nextPart;
    } else {
      parts.push(nextPart);
    }

    return {
      ...message,
      content: parts,
    };
  });
}

export function NovaAppShell() {
  const { t } = useTranslation();
  const [threads, setThreads] = useState<NovaThreadSummary[]>([]);
  const [messagesByThreadId, setMessagesByThreadId] = useState<
    Record<string, ThreadMessageLike[]>
  >({
    [DRAFT_THREAD_ID]: [createWelcomeMessage()],
  });
  const [currentThreadId, setCurrentThreadId] = useState(DRAFT_THREAD_ID);
  const [models, setModels] = useState<NovaModelRecord[]>([]);
  const [providers, setProviders] = useState<NovaProviderRecord[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(
    () => localStorage.getItem("nova-selected-model"),
  );
  const [isRunning, setIsRunning] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [composerText, setComposerText] = useState("");

  useEffect(() => {
    if (selectedModelId) {
      localStorage.setItem("nova-selected-model", selectedModelId);
    }
  }, [selectedModelId]);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  const currentMessages = messagesByThreadId[currentThreadId] || [];
  const activeThreadListId = threads.some(
    (thread) => thread.id === currentThreadId,
  )
    ? currentThreadId
    : undefined;

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      try {
        const [availableModels, availableProviders, savedSessions] =
          await Promise.all([listModels(), listProviders(), listSessions()]);

        if (cancelled) {
          return;
        }

        startTransition(() => {
          setModels(availableModels);
          setProviders(availableProviders);
          setThreads(savedSessions.map(toThreadSummary));
          if (availableModels.length > 0) {
            setSelectedModelId((current) => current || availableModels[0].id);
          }
        });
      } catch (error) {
        if (!cancelled) {
          console.error(error);
        }
      }
    }

    void bootstrap();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const handleLanguageChange = () => {
      setMessagesByThreadId((prev) => {
        const draft = prev[DRAFT_THREAD_ID];
        if (draft?.length === 1 && draft[0]?.id === "welcome") {
          return { ...prev, [DRAFT_THREAD_ID]: [createWelcomeMessage()] };
        }
        return prev;
      });
    };
    i18n.on("languageChanged", handleLanguageChange);
    return () => {
      i18n.off("languageChanged", handleLanguageChange);
    };
  }, []);

  async function loadThread(threadId: string) {
    try {
      const messages = await listMessages(threadId);
      startTransition(() => {
        setCurrentThreadId(threadId);
        setMessagesByThreadId((previous) => ({
          ...previous,
          [threadId]: toThreadMessages(messages),
        }));
      });
    } catch (error) {
      throw error;
    }
  }

  function setThreadMessages(
    threadId: string,
    updater:
      | ThreadMessageLike[]
      | ((messages: ThreadMessageLike[]) => ThreadMessageLike[]),
  ) {
    setMessagesByThreadId((previous) => {
      const current = previous[threadId] || [];
      return {
        ...previous,
        [threadId]: typeof updater === "function" ? updater(current) : updater,
      };
    });
  }

  function switchToDraftThread() {
    if (isRunning) {
      return;
    }

    startTransition(() => {
      setCurrentThreadId(DRAFT_THREAD_ID);
      setMessagesByThreadId((previous) => ({
        ...previous,
        [DRAFT_THREAD_ID]: previous[DRAFT_THREAD_ID] || [
          createWelcomeMessage(),
        ],
      }));
    });
    setComposerText("");
  }

  useEffect(() => {
    const textarea = composerRef.current;
    if (!textarea) {
      return;
    }

    textarea.style.height = "0px";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
  }, [composerText]);

  useEffect(() => {
    if (isRunning) {
      return;
    }

    const textarea = composerRef.current;
    if (!textarea) {
      return;
    }

    textarea.focus({ preventScroll: true });
    const caret = textarea.value.length;
    textarea.setSelectionRange(caret, caret);
  }, [currentThreadId, isRunning]);

  async function submitPrompt(prompt: string, attachments?: NovaAttachmentData[]) {
    if (!prompt) {
      return;
    }

    const selectedModel =
      models.find((item) => item.id === selectedModelId) || null;
    const originThreadId = currentThreadId;
    const userMessageId = crypto.randomUUID();
    const assistantMessageId = crypto.randomUUID();
    const userMessage = createTextMessage("user", prompt, userMessageId);
    const assistantMessage = createAssistantMessage(assistantMessageId);
    let activeThreadId = originThreadId;
    let requiresInput = false;

    setIsRunning(true);
    setComposerText("");

    setThreadMessages(originThreadId, (previous) => [
      ...buildDraftMessages(previous),
      userMessage,
      assistantMessage,
    ]);

    try {
      await streamChat({
        message: prompt,
        sessionId: originThreadId === DRAFT_THREAD_ID ? null : originThreadId,
        provider: selectedModel?.provider || null,
        model: selectedModel?.model || null,
        attachments,
        onEvent: (event) => {
          if (event.type === "data-nova-session") {
            const sessionId = String(event.data?.sessionId || "");
            if (!sessionId) {
              return;
            }

            activeThreadId = sessionId;
            startTransition(() => {
              setMessagesByThreadId((previous) => {
                const sourceMessages = previous[originThreadId] || [];
                return {
                  ...previous,
                  [sessionId]: sourceMessages,
                  [DRAFT_THREAD_ID]:
                    originThreadId === DRAFT_THREAD_ID
                      ? [createWelcomeMessage()]
                      : previous[DRAFT_THREAD_ID] || [createWelcomeMessage()],
                };
              });
              setCurrentThreadId(sessionId);
              setThreads((previous) => {
                const existing = previous.find(
                  (thread) => thread.id === sessionId,
                );
                return upsertThread(
                  previous,
                  existing ?? {
                    id: sessionId,
                    title: createOptimisticSessionTitle(prompt),
                    status: "regular",
                  },
                );
              });
            });
            return;
          }

          if (event.type === "text-delta") {
            setThreadMessages(activeThreadId, (previous) =>
              setAssistantText(
                previous,
                assistantMessageId,
                (text) => text + (event.delta || ""),
              ),
            );
            return;
          }

          if (event.type === "tool-input-start") {
            if (!event.toolCallId) {
              return;
            }
            const toolCallId = event.toolCallId;

            setThreadMessages(activeThreadId, (previous) =>
              upsertAssistantToolCall(previous, assistantMessageId, {
                toolCallId,
                toolName: event.toolName,
              }),
            );
            return;
          }

          if (event.type === "tool-input-available") {
            if (!event.toolCallId) {
              return;
            }
            const toolCallId = event.toolCallId;

            setThreadMessages(activeThreadId, (previous) =>
              upsertAssistantToolCall(previous, assistantMessageId, {
                toolCallId,
                toolName: event.toolName,
                input: event.input,
              }),
            );
            return;
          }

          if (event.type === "tool-output-available") {
            if (!event.toolCallId) {
              return;
            }
            const toolCallId = event.toolCallId;

            setThreadMessages(activeThreadId, (previous) =>
              upsertAssistantToolCall(previous, assistantMessageId, {
                toolCallId,
                output: event.output,
              }),
            );
            return;
          }

          if (event.type === "data-nova-input-required") {
            requiresInput = true;
            return;
          }

          if (event.type === "error") {
            throw new Error(event.errorText || "Unknown error");
          }
        },
      });

      if (requiresInput) {
        return;
      }
    } catch (error) {
      const messageText =
        error instanceof Error ? error.message : String(error);
      setThreadMessages(activeThreadId, (previous) =>
        setAssistantText(
          previous,
          assistantMessageId,
          () => `[error] ${messageText}`,
        ),
      );
    } finally {
      setIsRunning(false);
    }
  }

  async function handleComposerSubmit() {
    const prompt = composerText.trim();
    if (!prompt || isRunning) {
      return;
    }

    const composerState = runtime.thread.composer.getState();
    const pendingAttachments = composerState.attachments;

    let processedAttachments: NovaAttachmentData[] | undefined;
    if (pendingAttachments.length > 0) {
      const adapter = new CompositeAttachmentAdapter([
        new SimpleImageAttachmentAdapter(),
        new SimpleTextAttachmentAdapter(),
      ]);
      processedAttachments = [];
      for (const att of pendingAttachments) {
        if (att.status.type === "complete" && att.content) {
          processedAttachments.push(att as NovaAttachmentData);
        } else if (att.status.type === "requires-action" && att.file) {
          const result = await adapter.send(att);
          processedAttachments.push(result as NovaAttachmentData);
        }
      }
      runtime.thread.composer.clearAttachments();
    }

    await submitPrompt(prompt, processedAttachments);
  }

  function handleConfigModelsUpdated(nextModels: NovaModelRecord[]) {
    startTransition(() => {
      setModels(nextModels);
      setSelectedModelId((current) => {
        if (current && nextModels.some((model) => model.id === current)) {
          return current;
        }
        return nextModels[0]?.id ?? null;
      });
    });
  }

  async function refreshProviders() {
    const nextProviders = await listProviders();
    startTransition(() => {
      setProviders(nextProviders);
    });
  }

  function handleConfigStatus(message: string | null) {
    console.debug(message);
  }

  const runtime = useExternalStoreRuntime({
    messages: currentMessages,
    isRunning,
    onNew: async () => {},
    convertMessage: (message) => message,
    setMessages: (messages) => {
      setThreadMessages(currentThreadId, [...messages]);
    },
    adapters: {
      attachments: new CompositeAttachmentAdapter([
        new SimpleImageAttachmentAdapter(),
        new SimpleTextAttachmentAdapter(),
      ]),
      threadList: {
        threadId: activeThreadListId,
        threads,
        archivedThreads: [],
        onSwitchToNewThread: switchToDraftThread,
        onSwitchToThread: (threadId) => {
          if (isRunning || threadId === currentThreadId) {
            return;
          }
          void loadThread(threadId);
        },
      },
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <TooltipProvider>
        <div className="flex h-screen overflow-hidden bg-background text-foreground">
          <aside
            className={`sticky top-0 flex h-screen shrink-0 flex-col overflow-hidden bg-sidebar transition-[width,opacity] duration-200 ease-out ${
              isSidebarCollapsed
                ? "w-0 opacity-0"
                : "w-[280px] border-r opacity-100"
            }`}
          >
            {!isSidebarCollapsed && (
              <>
                <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
                  <ThreadList />
                </div>
                <div className="flex items-center justify-between border-t border-sidebar-border px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <div className="flex size-5 items-center justify-center rounded-md bg-sidebar-accent text-[10px] font-bold text-sidebar-accent-foreground">
                      N
                    </div>
                    <span className="text-sm font-medium text-sidebar-foreground">
                      Nova
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      i18n.changeLanguage(
                        i18n.language === "zh-CN" ? "en" : "zh-CN",
                      )
                    }
                    className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                    aria-label="Switch language"
                  >
                    <LanguagesIcon className="size-4" />
                  </button>
                </div>
              </>
            )}
          </aside>

          <main
            className="relative flex min-w-0 flex-1 flex-col overflow-hidden bg-background"
            style={{ ["--thread-max-width" as string]: "44rem" }}
          >
            <Button
              type="button"
              variant="outline"
              size="icon"
              className={`fixed top-4 z-30 rounded-full bg-background/90 shadow-sm backdrop-blur transition-[left] duration-200 ease-out ${
                isSidebarCollapsed ? "left-4" : "left-[296px]"
              }`}
              aria-label={
                isSidebarCollapsed
                  ? t("app.expandSidebar")
                  : t("app.collapseSidebar")
              }
              onClick={() => setIsSidebarCollapsed((value) => !value)}
            >
              {isSidebarCollapsed ? (
                <ChevronRightIcon className="size-4" />
              ) : (
                <ChevronLeftIcon className="size-4" />
              )}
            </Button>

            <div className="flex min-h-0 flex-1 flex-col">
              <Thread
                composer={{
                  ref: composerRef,
                  text: composerText,
                  isRunning,
                  onChange: setComposerText,
                  onSubmit: () => {
                    void handleComposerSubmit();
                  },
                  onKeyDown: (event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void handleComposerSubmit();
                    }
                  },
                }}
                modelSelection={{
                  models,
                  providers,
                  selectedModelId,
                  onSelect: setSelectedModelId,
                  onModelsUpdated: handleConfigModelsUpdated,
                  onProvidersRefresh: refreshProviders,
                  onStatusChange: handleConfigStatus,
                }}
              />
            </div>
          </main>
        </div>
      </TooltipProvider>
    </AssistantRuntimeProvider>
  );
}
