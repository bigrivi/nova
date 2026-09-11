/** ask_user interaction state: question form active/cleared (zustand) */
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

type AskUserState = {
    active: AskQuestion[] | null;
    setActive: (questions: AskQuestion[] | null) => void;
};

export const useAskUserStore = create<AskUserState>((set) => ({
    active: null,
    setActive: (questions) => set({ active: questions }),
}));
