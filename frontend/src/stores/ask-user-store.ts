import { create } from "zustand";

type AskUserStatus =
  | { readonly type: "running" }
  | { readonly type: "complete" }
  | { readonly type: "incomplete"; readonly reason: "length" | "other" | "cancelled" | "content-filter" | "error"; readonly error?: unknown }
  | { readonly type: "requires-action"; readonly reason: "interrupt" };

interface ActiveAskUser {
  args: unknown;
  argsText: string;
  resume: (payload: unknown) => void;
  result: unknown;
  status: AskUserStatus;
}

interface AskUserStore {
  active: ActiveAskUser | null;
  setActive: (call: ActiveAskUser | null) => void;
}

export const useAskUserStore = create<AskUserStore>((set) => ({
  active: null,
  setActive: (call) => set({ active: call }),
}));
