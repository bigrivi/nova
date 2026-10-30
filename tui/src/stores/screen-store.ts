/** Screen navigation state: currently open modal screen (zustand) */
import { create } from "zustand";

export type Screen =
    | { kind: "sessions" }
    | { kind: "models" }
    | { kind: "theme" }
    | { kind: "variants" }
    | { kind: "agents" }
    | { kind: "create-agent" }
    | { kind: "delete-agent" }
    | { kind: "permissions" }
    | { kind: "rewind" }
    | { kind: "tasks" }
    | { kind: "mcp" }
    | { kind: "memory" }
    | { kind: "diff" }
    | { kind: "commit" }
    | { kind: "schedules" }
    | { kind: "review" };

type ScreenState = {
    current: Screen | null;
    open: (screen: Screen) => void;
    close: () => void;
};

export const useScreenStore = create<ScreenState>((set) => ({
    current: null,
    open: (screen) => set({ current: screen }),
    close: () => set({ current: null }),
}));
