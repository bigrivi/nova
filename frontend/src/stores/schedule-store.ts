import { create } from "zustand";

import type { NovaScheduleJob } from "../types/nova";

type ScheduleStore = {
    schedules: NovaScheduleJob[];
    loading: boolean;
    error: string | null;
    setSchedules: (schedules: NovaScheduleJob[]) => void;
    upsertSchedule: (schedule: NovaScheduleJob) => void;
    removeSchedule: (id: string) => void;
    setLoading: (loading: boolean) => void;
    setError: (error: string | null) => void;
    reset: () => void;
};

const INITIAL: Pick<ScheduleStore, "schedules" | "loading" | "error"> = {
    schedules: [],
    loading: false,
    error: null,
};

export const useScheduleStore = create<ScheduleStore>((set) => ({
    ...INITIAL,
    setSchedules: (schedules) => set({ schedules, error: null }),
    upsertSchedule: (schedule) =>
        set((state) => {
            const index = state.schedules.findIndex(
                (item) => item.id === schedule.id,
            );
            if (index < 0) {
                return { schedules: [schedule, ...state.schedules] };
            }
            const next = [...state.schedules];
            next[index] = schedule;
            return { schedules: next };
        }),
    removeSchedule: (id) =>
        set((state) => ({
            schedules: state.schedules.filter((item) => item.id !== id),
        })),
    setLoading: (loading) => set({ loading }),
    setError: (error) => set({ error }),
    reset: () => set({ ...INITIAL }),
}));
