import { create } from "zustand";

type AskUserStatus =
    | { readonly type: "running" }
    | { readonly type: "complete" }
    | {
          readonly type: "incomplete";
          readonly reason:
              | "length"
              | "other"
              | "cancelled"
              | "content-filter"
              | "error";
          readonly error?: unknown;
      }
    | { readonly type: "requires-action"; readonly reason: "interrupt" };

export interface ActiveAskUser {
    args: unknown;
    argsText: string;
    resume: (payload: unknown) => void;
    result: unknown;
    status: AskUserStatus;
}

interface AskUserStore {
    active: ActiveAskUser | null;
    activeSessionId: string | null;
    activeBySession: Record<string, ActiveAskUser>;
    setActive: (call: ActiveAskUser | null) => void;
    setActiveForSession: (sessionId: string, call: ActiveAskUser | null) => void;
    clearActiveForSession: (sessionId: string) => void;
    syncActiveToSession: (sessionId: string | null) => void;
}

export const useAskUserStore = create<AskUserStore>((set) => ({
    active: null,
    activeSessionId: null,
    activeBySession: {},
    setActive: (call) => set({ active: call }),
    setActiveForSession: (sessionId, call) =>
        set((state) => {
            const next = { ...state.activeBySession };
            if (call) {
                next[sessionId] = call;
            } else {
                delete next[sessionId];
            }
            return {
                activeBySession: next,
                active:
                    state.activeSessionId === sessionId
                        ? call
                        : state.active,
            };
        }),
    clearActiveForSession: (sessionId) =>
        set((state) => {
            if (!(sessionId in state.activeBySession)) {
                return state;
            }
            const next = { ...state.activeBySession };
            delete next[sessionId];
            const isCurrent = state.activeSessionId === sessionId;
            return {
                activeBySession: next,
                active: isCurrent ? null : state.active,
                activeSessionId: isCurrent ? null : state.activeSessionId,
            };
        }),
    syncActiveToSession: (sessionId) =>
        set((state) => ({
            active:
                sessionId == null
                    ? null
                    : (state.activeBySession[sessionId] ?? null),
            activeSessionId: sessionId,
        })),
}));
