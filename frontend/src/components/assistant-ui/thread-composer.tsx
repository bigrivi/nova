import { ThreadStickyComposer } from "@/components/assistant-ui/thread-sticky-composer";
import type { NovaModelRecord, NovaProviderRecord } from "@/types/nova";
import { useAuiState } from "@assistant-ui/react";
import type { KeyboardEvent, RefObject } from "react";
import { type FC, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const GREETING_KEYS = [
    "app.welcomeGreeting1",
    "app.welcomeGreeting2",
    "app.welcomeGreeting3",
    "app.welcomeGreeting4",
    "app.welcomeGreeting5",
    "app.welcomeGreeting6",
    "app.welcomeGreeting7",
    "app.welcomeGreeting8",
] as const;

type ThreadComposer = {
    ref: RefObject<HTMLTextAreaElement | null>;
    text: string;
    isRunning: boolean;
    onChange: (value: string) => void;
    onSubmit: () => void;
    onCancel: () => void;
    onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
};

type ThreadModelSelection = {
    models: NovaModelRecord[];
    providers: NovaProviderRecord[];
    selectedModelId: string | null;
    onSelect: (modelId: string) => void;
    onModelsUpdated: (models: NovaModelRecord[]) => void;
    onProvidersRefresh: () => Promise<void>;
    onStatusChange: (message: string | null) => void;
};

type ThreadComposerContainerProps = {
    composer: ThreadComposer;
    modelSelection: ThreadModelSelection;
    onHeightChange?: (height: number) => void;
    hidden: boolean;
};

export const ThreadComposerContainer: FC<ThreadComposerContainerProps> = ({
    composer,
    modelSelection,
    onHeightChange,
    hidden,
}) => {
    const isEmpty = useAuiState((s) => s.thread.isEmpty);
    return (
        <div
            className={`pointer-events-none z-20${
                isEmpty
                    ? " absolute inset-0 flex items-center justify-center"
                    : " absolute inset-x-0 bottom-0"
            }${hidden ? " invisible" : ""}`}
        >
            <div
                className={`flex w-full flex-col${
                    isEmpty ? " max-w-(--thread-max-width) px-4" : ""
                }`}
            >
                {isEmpty && (
                    <Welcome />
                )}
                <ThreadStickyComposer
                    composer={composer}
                    modelSelection={modelSelection}
                    onHeightChange={onHeightChange}
                />
            </div>
        </div>
    );
};

const Welcome: FC = () => {
    const { t } = useTranslation();
    const [greeting, setGreeting] = useState<string | null>(null);

    useEffect(() => {
        const key = GREETING_KEYS[Math.floor(Math.random() * GREETING_KEYS.length)];
        setGreeting(t(key));
    }, [t]);

    return (
        greeting ? (
            <section className="mb-6 flex flex-col items-center px-4 text-center">
                <h1 className="text-3xl">{greeting}</h1>
            </section>
        ) : null
    );
};
