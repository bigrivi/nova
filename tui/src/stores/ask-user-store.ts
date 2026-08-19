/** ask_user interaction state: question form active/cleared (zustand) */
import { create } from "zustand";

export type AskQuestion = {
    id: string;
    header: string;
    question: string;
    inputType: "text" | "select" | "confirm";
    options: { label: string; value?: string }[];
    multiple: boolean;
    required: boolean;
};

type AskUserState = {
    active: AskQuestion[] | null;
    setActive: (questions: AskQuestion[] | null) => void;
};

export const useAskUserStore = create<AskUserState>((set) => ({
    active: null,
    setActive: (questions) => set({ active: questions }),
}));
