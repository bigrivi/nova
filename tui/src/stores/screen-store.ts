/** 屏幕导航状态：当前打开的模态屏幕（zustand） */
import { create } from 'zustand'

export type Screen =
  | { kind: 'sessions' }
  | { kind: 'models' }
  | { kind: 'agents' }
  | { kind: 'create-agent' }
  | { kind: 'delete-agent' }

type ScreenState = {
  current: Screen | null
  open: (screen: Screen) => void
  close: () => void
}

export const useScreenStore = create<ScreenState>((set) => ({
  current: null,
  open: (screen) => set({ current: screen }),
  close: () => set({ current: null }),
}))
