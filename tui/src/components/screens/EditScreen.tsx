/** `/edit`: pick a question to replace, then answer it again. */
import { useMemo } from "react";
import { listMessages } from "../../api/nova-api.ts";
import type { NovaMessageRecord } from "../../api/types.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useEditStore } from "../../stores/edit-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { relativeAge } from "./RewindScreen.tsx";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { SearchableList } from "./SearchableList.tsx";
import { useListScreen } from "./use-list-screen.ts";

const MAX_ROWS = 40;

/** The text the user sees, which is the text they typed. */
function questionText(message: NovaMessageRecord): string {
    return message.display_text || message.content || "";
}

/** One line of the question, for the list. */
function preview(text: string): string {
    const line = text.replace(/\s+/g, " ").trim();
    return line.length > 60 ? `${line.slice(0, 57)}...` : line;
}

export function EditScreen() {
    const sessionId = useChatStore((state) => state.sessionId);
    const { items, ready, error } = useListScreen(() =>
        sessionId ? listMessages(sessionId) : Promise.resolve([]),
    );

    // Only questions can be edited: an answer is the agent's, and replacing it
    // is what `/regenerate` is for.
    const questions = useMemo(
        () => items.filter((message) => message.role === "user"),
        [items],
    );

    if (!ready) {
        return <ScreenLoading message={error || "Loading questions..."} />;
    }

    if (questions.length === 0) {
        return (
            <ScreenLoading
                message={error || "No questions yet: nothing to edit"}
            />
        );
    }

    return (
        <SearchableList
            title="Edit a question"
            items={questions.slice(0, MAX_ROWS).map((message) => ({
                label: `${preview(questionText(message))} · ${relativeAge(message.time_created)}`,
                value: message.id,
            }))}
            onSelect={(value) => {
                const message = questions.find((entry) => entry.id === value);
                if (!message) return;
                // The composer holds the text until it is sent or abandoned.
                useEditStore.getState().set(message.id, questionText(message));
                useScreenStore.getState().close();
            }}
            onClose={() => useScreenStore.getState().close()}
            emptyText={error || "no questions"}
        />
    );
}
