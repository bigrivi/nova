import { ThreadStickyComposer } from "@/components/assistant-ui/thread-sticky-composer";
import type { NovaModelRecord, NovaProviderRecord } from "@/types/nova";
import { type ThreadSuggestion, useAuiState } from "@assistant-ui/react";
import { type FC, useState } from "react";
import type { KeyboardEvent, RefObject } from "react";

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
  const suggestions = useAuiState((s) => s.thread?.suggestions);

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
        {isEmpty && <ComposerSuggestion suggestions={suggestions ?? []} />}
        <ThreadStickyComposer
          composer={composer}
          modelSelection={modelSelection}
          onHeightChange={onHeightChange}
        />
      </div>
    </div>
  );
};

const ComposerSuggestion: FC<{
  suggestions: readonly ThreadSuggestion[];
}> = ({ suggestions }) => {
  const [index] = useState<number | null>(() =>
    suggestions.length > 0
      ? Math.floor(Math.random() * suggestions.length)
      : null,
  );

  if (index === null || index >= suggestions.length) {
    return null;
  }

  return (
    <h2 className="mb-4 text-center text-lg font-normal text-muted-foreground">
      {suggestions[index].prompt}
    </h2>
  );
};
