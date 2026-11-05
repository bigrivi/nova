import { create } from "zustand";

export type Screen = "sessions" | "chat" | "settings";

type UiState = {
    screen: Screen;
    setScreen: (screen: Screen) => void;
};

export const useUi = create<UiState>((set) => ({
    screen: "sessions",
    setScreen: (screen) => set({ screen }),
}));
