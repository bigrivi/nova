/** ask_user 交互状态：问题表单激活/清除（zustand） */
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
