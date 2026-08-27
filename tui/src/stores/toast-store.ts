import { create } from "zustand";

type ToastState = {
    message: string | null;
    show: (message: string, duration?: number) => void;
    hide: () => void;
};

let timer: ReturnType<typeof setTimeout> | null = null;

export const useToastStore = create<ToastState>((set) => ({
    message: null,
    show: (message, duration = 2000) => {
        if (timer) clearTimeout(timer);
        set({ message });
        timer = setTimeout(() => set({ message: null }), duration);
    },
    hide: () => {
        if (timer) clearTimeout(timer);
        set({ message: null });
    },
}));
