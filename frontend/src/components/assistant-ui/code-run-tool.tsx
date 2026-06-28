"use client";

import Prism from "prismjs";
import "prismjs/components/prism-python";
import "prismjs/themes/prism-tomorrow.css";
import { cn } from "@/lib/utils";
import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { memo, useMemo } from "react";
import {
  ToolFallbackContent,
  ToolFallbackError,
  ToolFallbackResult,
  ToolFallbackRoot,
  ToolFallbackTrigger,
} from "./tool-fallback";

const CodeRunToolImpl: ToolCallMessagePartComponent = ({
  toolName,
  argsText,
  result,
  status,
}) => {
  let code = "";
  let description = "";
  try {
    const parsed = JSON.parse(argsText || "{}");
    code = parsed.code || "";
    description = parsed.description || "";
  } catch {}

  const highlightedHtml = useMemo(() => {
    if (!code) return null;
    const grammar = Prism.languages.python;
    if (!grammar) return null;
    return Prism.highlight(code, grammar, "python");
  }, [code]);

  const isCancelled =
    status?.type === "incomplete" && status.reason === "cancelled";

  return (
    <ToolFallbackRoot
      className={cn(isCancelled && "border-muted-foreground/30 bg-muted/30")}
    >
      <ToolFallbackTrigger toolName="code_run (Python)" status={status} />
      <ToolFallbackContent>
        <ToolFallbackError status={status} />
        {code && (
          <div data-slot="tool-fallback-args" className="px-4">
            {description && (
              <p className="mb-2 text-xs text-muted-foreground">{description}</p>
            )}
            <pre className="whitespace-pre-wrap rounded-lg bg-[#1e1e1e] p-3 text-sm leading-relaxed overflow-x-auto">
              {highlightedHtml ? (
                <code
                  className="language-python"
                  dangerouslySetInnerHTML={{ __html: highlightedHtml }}
                />
              ) : (
                <code>{code}</code>
              )}
            </pre>
          </div>
        )}
        {!isCancelled && <ToolFallbackResult result={result} />}
      </ToolFallbackContent>
    </ToolFallbackRoot>
  );
};

export const CodeRunTool = memo(CodeRunToolImpl);
