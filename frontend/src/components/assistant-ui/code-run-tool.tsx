"use client";

import { cn } from "@/lib/utils";
import { errorTextFromResult } from "@/lib/tool-result";
import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import Prism from "prismjs";
import "prismjs/components/prism-python";
import { memo, useMemo } from "react";
import {
    ToolFallbackContent,
    ToolFallbackError,
    ToolFallbackResult,
    ToolFallbackRoot,
    ToolFallbackTrigger,
} from "./tool-fallback";

const CodeRunToolImpl: ToolCallMessagePartComponent = ({
    argsText,
    result,
    status,
    isError,
}) => {
    let code = "";
    let description = "";
    try {
        const parsed = JSON.parse(argsText || "{}");
        code = parsed.code || "";
        description = parsed.description || "";
    } catch (error) {
        if (!(error instanceof SyntaxError)) throw error;
    }

    const highlightedHtml = useMemo(() => {
        if (!code) return null;
        const grammar = Prism.languages.python;
        if (!grammar) return null;
        return Prism.highlight(code, grammar, "python");
    }, [code]);

    const isCancelled =
        status?.type === "incomplete" && status.reason === "cancelled";
    const errored = isError === true;

    return (
        <ToolFallbackRoot
            className={cn((isCancelled || errored) && "opacity-80")}
        >
            <ToolFallbackTrigger
                toolName="code_run"
                argsText={argsText}
                status={status}
                isError={isError}
            />
            <ToolFallbackContent>
                <ToolFallbackError
                    status={status}
                    message={errored ? errorTextFromResult(result) : null}
                />
                {code && (
                    <div data-slot="tool-fallback-args" className="w-full min-w-0 max-w-full">
                        {description && (
                            <p className="mb-2 font-sans text-xs font-normal text-muted-foreground break-words">
                                {description}
                            </p>
                        )}
                        <pre className="max-w-full overflow-x-auto whitespace-pre-wrap break-words rounded-lg border border-[#D6D2C7] bg-white p-3 font-mono text-sm leading-relaxed [tab-size:4]">
                            {highlightedHtml ? (
                                <code
                                    className="language-python font-mono! [tab-size:4]! bg-transparent! whitespace-pre-wrap! break-words!"
                                    dangerouslySetInnerHTML={{
                                        __html: highlightedHtml,
                                    }}
                                />
                            ) : (
                                <code>{code}</code>
                            )}
                        </pre>
                    </div>
                )}
                {!isCancelled && !errored && (
                    <ToolFallbackResult result={result} />
                )}
            </ToolFallbackContent>
        </ToolFallbackRoot>
    );
};

export const CodeRunTool = memo(CodeRunToolImpl);
