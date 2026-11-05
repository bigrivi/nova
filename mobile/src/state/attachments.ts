/** Attachments staged in a composer, one list per tab. */
import { create } from "zustand";

export type PendingImageAttachment = {
    kind: "image";
    id: string;
    name: string;
    contentType: string;
    /** `data:image/jpeg;base64,...`, already downscaled. */
    dataUrl: string;
    /** Local file URI or data URI used for the thumbnail. */
    previewUri: string;
};

export type PendingDocumentAttachment = {
    kind: "document";
    id: string;
    name: string;
    contentType: string;
    /** Plain UTF-8 text; the server folds this into the prompt. */
    text: string;
};

export type PendingAttachment =
    | PendingImageAttachment
    | PendingDocumentAttachment;

type AttachmentsState = {
    byTab: Record<string, PendingAttachment[]>;
    add: (tabId: string, attachment: PendingAttachment) => void;
    remove: (tabId: string, attachmentId: string) => void;
    clear: (tabId: string) => void;
    reset: () => void;
};

export const useAttachments = create<AttachmentsState>((set) => ({
    byTab: {},
    add: (tabId, attachment) =>
        set((state) => ({
            byTab: {
                ...state.byTab,
                [tabId]: [...(state.byTab[tabId] ?? []), attachment],
            },
        })),
    remove: (tabId, attachmentId) =>
        set((state) => {
            const current = state.byTab[tabId];
            if (!current) {
                return state;
            }
            return {
                byTab: {
                    ...state.byTab,
                    [tabId]: current.filter((item) => item.id !== attachmentId),
                },
            };
        }),
    clear: (tabId) =>
        set((state) => {
            if (!(tabId in state.byTab)) {
                return state;
            }
            const byTab = { ...state.byTab };
            delete byTab[tabId];
            return { byTab };
        }),
    reset: () => set({ byTab: {} }),
}));
