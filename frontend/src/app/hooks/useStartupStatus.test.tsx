// @vitest-environment jsdom
//
// Startup status, tested against the failure its comment describes.
//
// The voice half of this hook exists because a reload used to leave an in-flight
// recording invisible: the composer showed a start button, the backend answered
// 409, and the elapsed clock read zero for a take that had been running. Both
// halves of that are easy to lose and neither fails loudly, so both are pinned.

import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchAppVersion, getSpeechStatus } from "../../lib/nova-api";
import { useSpeechStore } from "../../stores/speech-store";
import { useStartupStatus } from "./useStartupStatus";

vi.mock("../../lib/nova-api", () => ({
    fetchAppVersion: vi.fn(),
    getSpeechStatus: vi.fn(),
}));

const fetchAppVersionMock = vi.mocked(fetchAppVersion);
const getSpeechStatusMock = vi.mocked(getSpeechStatus);

beforeEach(() => {
    vi.clearAllMocks();
    fetchAppVersionMock.mockResolvedValue(null);
    getSpeechStatusMock.mockResolvedValue({ enabled: false });
    useSpeechStore.setState({ enabled: false, phase: "idle", startedAt: null });
});

afterEach(() => {
    useSpeechStore.setState({ enabled: false, phase: "idle", startedAt: null });
});

describe("useStartupStatus", () => {
    it("exposes the version the backend reports", async () => {
        fetchAppVersionMock.mockResolvedValue("1.4.2");

        const { result } = renderHook(() => useStartupStatus());

        await waitFor(() => expect(result.current.appVersion).toBe("1.4.2"));
    });

    it("stays null rather than failing when the version is unavailable", async () => {
        // The badge is decoration. A backend too old to answer must not take the
        // whole shell down with it.
        fetchAppVersionMock.mockRejectedValue(new Error("no such endpoint"));

        const { result } = renderHook(() => useStartupStatus());

        await waitFor(() => expect(fetchAppVersionMock).toHaveBeenCalled());
        expect(result.current.appVersion).toBeNull();
    });

    it("lets the backend decide whether the microphone is offered", async () => {
        getSpeechStatusMock.mockResolvedValue({ enabled: true });

        renderHook(() => useStartupStatus());

        await waitFor(() => expect(useSpeechStore.getState().enabled).toBe(true));
    });

    it("adopts a recording that outlived a reload", async () => {
        // Without this the composer offers a start button for a take the backend
        // is already running, and pressing it is a 409.
        getSpeechStatusMock.mockResolvedValue({
            enabled: true,
            recording: true,
            recording_since_ms: 1_700_000_000_000,
        });

        renderHook(() => useStartupStatus());

        await waitFor(() =>
            expect(useSpeechStore.getState().phase).toBe("recording"),
        );
    });

    it("carries the backend's clock, not the moment the page loaded", async () => {
        // The elapsed readout is the whole point of `startedAt`. Falling back to
        // Date.now() would show a take that keeps starting over at 0:00 after
        // every reload, which reads as the recording being stuck.
        const began = 1_700_000_000_000;
        getSpeechStatusMock.mockResolvedValue({
            enabled: true,
            recording: true,
            recording_since_ms: began,
        });

        renderHook(() => useStartupStatus());

        await waitFor(() =>
            expect(useSpeechStore.getState().startedAt).toBe(began),
        );
    });

    it("falls back to now when the backend gave no start time", async () => {
        // An older backend may omit the field. A recording is still a recording.
        const before = Date.now();
        getSpeechStatusMock.mockResolvedValue({
            enabled: true,
            recording: true,
        });

        renderHook(() => useStartupStatus());

        await waitFor(() =>
            expect(useSpeechStore.getState().phase).toBe("recording"),
        );
        expect(useSpeechStore.getState().startedAt).toBeGreaterThanOrEqual(before);
    });

    it("leaves the phase alone when nothing is recording", async () => {
        // A local take in progress must survive this read. Writing "idle" over it
        // would strand the composer mid-recording, which is the same class of
        // breakage as the 409 it was written to avoid.
        useSpeechStore.setState({ phase: "transcribing", startedAt: 42 });
        getSpeechStatusMock.mockResolvedValue({ enabled: true, recording: false });

        renderHook(() => useStartupStatus());

        await waitFor(() => expect(useSpeechStore.getState().enabled).toBe(true));
        expect(useSpeechStore.getState().phase).toBe("transcribing");
        expect(useSpeechStore.getState().startedAt).toBe(42);
    });

    it("writes nothing after unmount", async () => {
        // Both reads can resolve after the shell is gone. An unguarded write here
        // turns the microphone on for a view that no longer exists.
        let release: (status: { enabled: boolean }) => void = () => {};
        getSpeechStatusMock.mockReturnValue(
            new Promise((resolve) => {
                release = resolve;
            }),
        );

        const { unmount } = renderHook(() => useStartupStatus());
        unmount();
        release({ enabled: true });
        await Promise.resolve();
        await Promise.resolve();

        expect(useSpeechStore.getState().enabled).toBe(false);
    });
});
