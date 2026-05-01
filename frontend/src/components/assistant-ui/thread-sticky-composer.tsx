import { ArrowUpIcon, LoaderCircleIcon } from "lucide-react";
import { useEffect, useRef, type KeyboardEvent, type RefObject } from "react";

import { ModelSelector } from "./model-selector";
import { Button } from "../ui/button";
import type { NovaModelRecord, NovaProviderRecord } from "../../types/nova";

type ThreadStickyComposerProps = {
  composer: {
    ref: RefObject<HTMLTextAreaElement | null>;
    text: string;
    isRunning: boolean;
    onChange: (value: string) => void;
    onSubmit: () => void;
    onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  };
  status: {
    text: string;
    error: string | null;
  };
  modelSelection: {
    models: NovaModelRecord[];
    providers: NovaProviderRecord[];
    selectedModelId: string | null;
    onSelect: (modelId: string) => void;
    onModelsUpdated: (models: NovaModelRecord[]) => void;
    onProvidersRefresh: () => Promise<void>;
    onStatusChange: (message: string | null) => void;
  };
  onHeightChange?: (height: number) => void;
};

export function ThreadStickyComposer({
  composer,
  status,
  modelSelection,
  onHeightChange,
}: ThreadStickyComposerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = containerRef.current;
    if (!node || !onHeightChange) {
      return;
    }

    const reportHeight = () => {
      onHeightChange(node.offsetHeight);
    };

    reportHeight();

    const observer = new ResizeObserver(() => {
      reportHeight();
    });
    observer.observe(node);

    return () => {
      observer.disconnect();
      onHeightChange(0);
    };
  }, [onHeightChange]);

  return (
    <div ref={containerRef} className="pointer-events-none relative pb-3 pt-3">
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-0 h-10 bg-background/96 backdrop-blur" />
      <div className="relative z-10 mx-auto w-full max-w-(--thread-max-width) px-4">
        <div className="pointer-events-auto rounded-[24px] border bg-background p-3 shadow-sm transition-shadow focus-within:border-ring/75 focus-within:ring-2 focus-within:ring-ring/20">
          <textarea
            ref={composer.ref}
            value={composer.text}
            rows={1}
            disabled={composer.isRunning}
            placeholder="Send a message..."
            aria-label="Message input"
            className="max-h-40 min-h-10 w-full resize-none bg-transparent px-1 py-1 text-sm outline-none placeholder:text-muted-foreground/80 disabled:cursor-not-allowed"
            onChange={(event) => composer.onChange(event.target.value)}
            onKeyDown={composer.onKeyDown}
          />

          <div className="mt-3 flex items-center justify-between gap-3">
            <div
              className={`text-xs ${
                status.error ? "text-destructive" : "text-muted-foreground"
              }`}
            >
              {status.error || status.text}
            </div>

            <div className="flex items-center gap-2">
              <ModelSelector
                compact
                models={modelSelection.models}
                providers={modelSelection.providers}
                selectedModelId={modelSelection.selectedModelId}
                onSelect={modelSelection.onSelect}
                onModelsUpdated={modelSelection.onModelsUpdated}
                onProvidersRefresh={modelSelection.onProvidersRefresh}
                onStatusChange={modelSelection.onStatusChange}
              />

              <Button
                type="button"
                size="icon"
                className="rounded-full"
                disabled={composer.isRunning || composer.text.trim().length === 0}
                onClick={composer.onSubmit}
              >
                {composer.isRunning ? (
                  <LoaderCircleIcon className="size-4 animate-spin" />
                ) : (
                  <ArrowUpIcon className="size-4" />
                )}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
