/** Whether the session panel is open.
 *
 *  The presentation is not stored: it follows the terminal width, so the same
 *  panel docks on a wide terminal and takes the screen on a narrow one.
 */
import { create } from "zustand";

type SidebarState = {
    open: boolean;
    toggle: () => void;
    setOpen: (open: boolean) => void;
};

export const useSidebarStore = create<SidebarState>((set) => ({
    open: false,
    toggle: () => set((state) => ({ open: !state.open })),
    setOpen: (open) => set({ open }),
}));
