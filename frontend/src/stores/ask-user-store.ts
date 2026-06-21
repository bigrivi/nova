import { create } from "zustand";

interface ActiveAskUser {
  args: unknown;
  argsText: string;
  resume: (text: string) => void;
  result: unknown;
  status: { type: string };
}

interface AskUserStore {
  active: ActiveAskUser | null;
  setActive: (call: ActiveAskUser | null) => void;
}

export const useAskUserStore = create<AskUserStore>((set) => ({
  active: null,
  setActive: (call) => set({ active: call }),
}));
