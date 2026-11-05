/** ask_user interaction state: one visible form plus a FIFO for concurrent tabs. */
import { create } from "zustand";

export type AskOption = {
    label: string;
    value?: string;
    description?: string;
};

export type AskQuestion = {
    id: string;
    header: string;
    question: string;
    inputType: "text" | "textarea" | "select";
    options: AskOption[];
    multiple: boolean;
    required: boolean;
    default?: string;
};

type AskEntry = { tabId: string | null; questions: AskQuestion[] };

type AskUserState = {
    active: AskQuestion[] | null;
    /** The tab that owns *active*, so the shell can switch to it. */
    activeTabId: string | null;
    queue: AskEntry[];
    /** Null clears the visible form and promotes the next queued question. */
    setActive: (questions: AskQuestion[] | null, tabId?: string | null) => void;
    clearTab: (tabId: string) => void;
};

function promote(queue: AskEntry[]): AskEntry | null {
    return queue[0] ?? null;
}

function sameQuestions(a: AskQuestion[], b: AskQuestion[]): boolean {
    return JSON.stringify(a) === JSON.stringify(b);
}

export const useAskUserStore = create<AskUserState>((set) => ({
    active: null,
    activeTabId: null,
    queue: [],

    setActive: (questions, tabId = null) =>
        set((state) => {
            if (questions === null) {
                const next = promote(state.queue);
                return {
                    active: next?.questions ?? null,
                    activeTabId: next?.tabId ?? null,
                    queue: state.queue.slice(1),
                };
            }
            if (state.active === null) {
                return { active: questions, activeTabId: tabId, queue: state.queue };
            }
            if (
                state.activeTabId === tabId &&
                sameQuestions(state.active, questions)
            ) {
                return state;
            }
            if (
                state.queue.some(
                    (entry) =>
                        entry.tabId === tabId &&
                        sameQuestions(entry.questions, questions),
                )
            ) {
                return state;
            }
            return {
                active: state.active,
                activeTabId: state.activeTabId,
                queue: [...state.queue, { tabId, questions }],
            };
        }),

    clearTab: (tabId) =>
        set((state) => {
            const queue = state.queue.filter((entry) => entry.tabId !== tabId);
            if (state.activeTabId !== tabId) {
                return { queue };
            }
            const next = promote(queue);
            return {
                active: next?.questions ?? null,
                activeTabId: next?.tabId ?? null,
                queue: queue.slice(next ? 1 : 0),
            };
        }),
}));
