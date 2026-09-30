"use client";

import { TextMessagePartProvider } from "@assistant-ui/react";
import {
    type CodeHeaderProps,
    MarkdownTextPrimitive,
    type SyntaxHighlighterProps,
    unstable_memoizeMarkdownComponents as memoizeMarkdownComponents,
    useIsMarkdownCodeBlock,
} from "@assistant-ui/react-markdown";
import { CheckIcon, CopyIcon, TriangleAlertIcon } from "lucide-react";
import Prism from "prismjs";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-csharp";
import "prismjs/components/prism-diff";
import "prismjs/components/prism-docker";
import "prismjs/components/prism-go";
import "prismjs/components/prism-java";
import "prismjs/components/prism-json";
import "prismjs/components/prism-jsx";
import "prismjs/components/prism-markdown";
import "prismjs/components/prism-python";
import "prismjs/components/prism-ruby";
import "prismjs/components/prism-rust";
import "prismjs/components/prism-sql";
import "prismjs/components/prism-tsx";
import "prismjs/components/prism-typescript";
import "prismjs/components/prism-yaml";
import { type FC, memo, type ReactNode, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import remarkGfm from "remark-gfm";

import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { cn } from "@/lib/utils";

const PRISM_LANGUAGE_ALIASES: Record<string, string> = {
    csharp: "csharp",
    docker: "docker",
    dockerfile: "docker",
    js: "javascript",
    jsx: "jsx",
    md: "markdown",
    py: "python",
    rb: "ruby",
    rs: "rust",
    sh: "bash",
    shell: "bash",
    ts: "typescript",
    tsx: "tsx",
    yml: "yaml",
    zsh: "bash",
};

function normalizePrismLanguage(language: string | undefined) {
    if (!language) {
        return null;
    }

    const normalized = language
        .replace(/^language-/, "")
        .trim()
        .toLowerCase()
        .split(/[\s{]/)[0];

    if (!normalized) {
        return null;
    }

    return PRISM_LANGUAGE_ALIASES[normalized] ?? normalized;
}

function ensurePrismLanguage(language: string | undefined) {
    const normalized = normalizePrismLanguage(language);
    if (!normalized) {
        return null;
    }

    return Prism.languages[normalized] ? normalized : null;
}

const MarkdownSyntaxHighlighter: FC<SyntaxHighlighterProps> = ({
    components: { Pre, Code },
    language,
    code,
}) => {
    const resolvedLanguage = useMemo(
        () => ensurePrismLanguage(language),
        [language],
    );
    const className = resolvedLanguage
        ? `language-${resolvedLanguage}`
        : undefined;
    const highlightedHtml = useMemo(() => {
        if (!resolvedLanguage) {
            return null;
        }

        const grammar = Prism.languages[resolvedLanguage];
        if (!grammar) {
            return null;
        }

        return Prism.highlight(code, grammar, resolvedLanguage);
    }, [code, resolvedLanguage]);

    if (!highlightedHtml) {
        return (
            <Pre className={className}>
                <Code
                    className={cn(
                        className,
                        "font-mono! [tab-size:4]! bg-transparent! leading-relaxed!",
                    )}
                >
                    {code}
                </Code>
            </Pre>
        );
    }

    return (
        <Pre className={className}>
            <Code
                className={cn(
                    className,
                    "font-mono! [tab-size:4]! bg-transparent! leading-relaxed!",
                )}
                dangerouslySetInnerHTML={{ __html: highlightedHtml }}
            />
        </Pre>
    );
};

/**
 * Render markdown from an explicit string.
 *
 * `MarkdownTextPrimitive` takes no text: it reads `useMessagePartText()` and
 * sets its own children after spreading props, so anything passed as `text`
 * would be silently ignored and the surrounding part rendered instead. A
 * sub-agent report lives in a prop on a collapsible rather than in the part
 * being rendered, so it needs its own part scope to render from.
 *
 * `defaultComponents` is referenced inside render, not at module scope: it is a
 * `const` declared further down this file, and spreading it during module
 * evaluation hits the temporal dead zone.
 */
const MarkdownBodyImpl: FC<{ text: string; className?: string }> = ({
    text,
    className,
}) => (
    <TextMessagePartProvider text={text}>
        <MarkdownTextPrimitive
            remarkPlugins={[remarkGfm]}
            className={cn("aui-md", className)}
            components={{
                ...defaultComponents,
                SyntaxHighlighter: MarkdownSyntaxHighlighter,
            }}
        />
    </TextMessagePartProvider>
);

export const MarkdownBody = memo(MarkdownBodyImpl);

const MarkdownTextImpl = () => {
    return (
        <MarkdownTextPrimitive
            remarkPlugins={[remarkGfm]}
            className="aui-md"
            components={{
                ...defaultComponents,
                SyntaxHighlighter: MarkdownSyntaxHighlighter,
            }}
        />
    );
};

export const MarkdownText = memo(MarkdownTextImpl);

const CodeHeader: FC<CodeHeaderProps> = ({ language, code }) => {
    const { t } = useTranslation();
    const { isCopied, copyToClipboard } = useCopyToClipboard();
    const onCopy = () => {
        if (!code || isCopied) return;
        copyToClipboard(code);
    };

    return (
        <div className="aui-code-header-root mt-2.5 flex items-center rounded-t-lg border border-border bg-muted/50 px-3 py-1.5 text-xs">
            {language && language !== "unknown" && (
                <span className="aui-code-header-language font-medium text-muted-foreground lowercase">
                    {language}
                </span>
            )}
            <TooltipIconButton
                tooltip={t("common.copy")}
                onClick={onCopy}
                className="ml-auto"
            >
                {!isCopied && <CopyIcon />}
                {isCopied && <CheckIcon />}
            </TooltipIconButton>
        </div>
    );
};

function legacyCopy(value: string): boolean {
    try {
        const textarea = document.createElement("textarea");
        textarea.value = value;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        const ok = document.execCommand("copy");
        document.body.removeChild(textarea);
        return ok;
    } catch {
        return false;
    }
}

const useCopyToClipboard = ({
    copiedDuration = 3000,
}: {
    copiedDuration?: number;
} = {}) => {
    const [isCopied, setIsCopied] = useState<boolean>(false);

    const copyToClipboard = (value: string) => {
        if (!value) return;

        const markCopied = () => {
            setIsCopied(true);
            setTimeout(() => setIsCopied(false), copiedDuration);
        };
        if (
            typeof navigator !== "undefined" &&
            navigator.clipboard?.writeText
        ) {
            navigator.clipboard.writeText(value).then(markCopied, () => {
                if (legacyCopy(value)) {
                    markCopied();
                }
            });
            return;
        }
        if (legacyCopy(value)) {
            markCopied();
        }
    };

    return { isCopied, copyToClipboard };
};

// Sentinel that appendFailureNotice() prepends to a failed turn's reason (see
// lib/thread-stream.ts). It is rendered as a distinct error callout instead of
// plain body text, so a failure reads as an error rather than as the answer.
const FAILURE_NOTICE_PREFIX = "[error] ";

function failureNoticeLead(children: ReactNode): string | null {
    if (typeof children === "string") return children;
    if (Array.isArray(children) && typeof children[0] === "string") {
        return children[0];
    }
    return null;
}

function stripFailurePrefix(children: ReactNode): ReactNode {
    if (typeof children === "string") {
        return children.slice(FAILURE_NOTICE_PREFIX.length);
    }
    if (Array.isArray(children) && typeof children[0] === "string") {
        const [first, ...rest] = children;
        return [first.slice(FAILURE_NOTICE_PREFIX.length), ...rest];
    }
    return children;
}

const defaultComponents = memoizeMarkdownComponents({
    h1: ({ className, ...props }) => (
        <h1
            className={cn(
                "aui-md-h1 mb-2 scroll-m-20 font-semibold text-base first:mt-0 last:mb-0",
                className,
            )}
            {...props}
        />
    ),
    h2: ({ className, ...props }) => (
        <h2
            className={cn(
                "aui-md-h2 mt-3 mb-1.5 scroll-m-20 font-semibold text-sm first:mt-0 last:mb-0",
                className,
            )}
            {...props}
        />
    ),
    h3: ({ className, ...props }) => (
        <h3
            className={cn(
                "aui-md-h3 mt-2.5 mb-1 scroll-m-20 font-semibold text-sm first:mt-0 last:mb-0",
                className,
            )}
            {...props}
        />
    ),
    h4: ({ className, ...props }) => (
        <h4
            className={cn(
                "aui-md-h4 mt-2 mb-1 scroll-m-20 font-medium text-sm first:mt-0 last:mb-0",
                className,
            )}
            {...props}
        />
    ),
    h5: ({ className, ...props }) => (
        <h5
            className={cn(
                "aui-md-h5 mt-2 mb-1 font-medium text-sm first:mt-0 last:mb-0",
                className,
            )}
            {...props}
        />
    ),
    h6: ({ className, ...props }) => (
        <h6
            className={cn(
                "aui-md-h6 mt-2 mb-1 font-medium text-sm first:mt-0 last:mb-0",
                className,
            )}
            {...props}
        />
    ),
    p: ({ className, children, ...props }) => {
        const lead = failureNoticeLead(children);
        if (lead?.startsWith(FAILURE_NOTICE_PREFIX)) {
            return (
                <div
                    data-slot="assistant-failure-notice"
                    className="aui-md-error my-2.5 flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-destructive first:mt-0 last:mb-0"
                >
                    <TriangleAlertIcon
                        className="mt-0.5 size-4 shrink-0"
                        aria-hidden="true"
                    />
                    <span className="aui-md-error-text min-w-0 leading-normal break-words">
                        {stripFailurePrefix(children)}
                    </span>
                </div>
            );
        }
        return (
            <p
                className={cn(
                    "aui-md-p my-2.5 leading-normal first:mt-0 last:mb-0",
                    className,
                )}
                {...props}
            >
                {children}
            </p>
        );
    },
    a: ({ className, ...props }) => (
        <a
            className={cn(
                "aui-md-a text-primary underline underline-offset-2 hover:text-primary/80",
                className,
            )}
            {...props}
        />
    ),
    blockquote: ({ className, ...props }) => (
        <blockquote
            className={cn(
                "aui-md-blockquote my-2.5 border-muted-foreground/30 border-s-2 ps-3 text-muted-foreground italic",
                className,
            )}
            {...props}
        />
    ),
    ul: ({ className, ...props }) => (
        <ul
            className={cn(
                "aui-md-ul my-2 ms-4 list-disc marker:text-muted-foreground [&>li]:mt-1",
                className,
            )}
            {...props}
        />
    ),
    ol: ({ className, ...props }) => (
        <ol
            className={cn(
                "aui-md-ol my-2 ms-4 list-decimal marker:text-weak-strong [&>li]:mt-1",
                className,
            )}
            {...props}
        />
    ),
    hr: ({ className, ...props }) => (
        <hr
            className={cn(
                "aui-md-hr my-2 border-muted-foreground/20",
                className,
            )}
            {...props}
        />
    ),
    table: ({ className, ...props }) => (
        <div className="aui-md-table-wrap my-2 w-full max-w-full overflow-x-auto">
            <table
                className={cn(
                    "aui-md-table w-full border-separate border-spacing-0",
                    className,
                )}
                {...props}
            />
        </div>
    ),
    th: ({ className, ...props }) => (
        <th
            className={cn(
                "aui-md-th border-s border-t border-b border-border bg-muted px-2 py-1 text-start font-medium last:border-e first:rounded-ss-lg last:rounded-se-lg [[align=center]]:text-center [[align=right]]:text-right",
                className,
            )}
            {...props}
        />
    ),
    td: ({ className, ...props }) => (
        <td
            className={cn(
                "aui-md-td border-s border-b border-border px-2 py-1 text-start break-words last:border-e [[align=center]]:text-center [[align=right]]:text-right",
                className,
            )}
            {...props}
        />
    ),
    tr: ({ className, ...props }) => (
        <tr
            className={cn(
                "aui-md-tr m-0 even:bg-muted/40 [&:hover>td]:bg-muted/60 [&:last-child>td:first-child]:rounded-es-lg [&:last-child>td:last-child]:rounded-ee-lg",
                className,
            )}
            {...props}
        />
    ),
    li: ({ className, ...props }) => (
        <li className={cn("aui-md-li leading-normal", className)} {...props} />
    ),
    sup: ({ className, ...props }) => (
        <sup
            className={cn(
                "aui-md-sup [&>a]:text-xs [&>a]:no-underline",
                className,
            )}
            {...props}
        />
    ),
    pre: ({ className, ...props }) => (
        <pre
            className={cn(
                "aui-md-pre my-0! overflow-x-auto rounded-t-none! rounded-b-lg! border border-border border-t-0 bg-card! p-3! font-mono! text-xs! leading-relaxed! [tab-size:4]!",
                className,
            )}
            {...props}
        />
    ),
    code: function Code({ className, ...props }) {
        const isCodeBlock =
            useIsMarkdownCodeBlock() ||
            Boolean(className?.includes("language-"));
        return (
            <code
                className={cn(
                    !isCodeBlock &&
                        "aui-md-inline-code rounded border border-code-border bg-code-bg px-1.5 py-0.5 font-mono text-[0.85em] text-code-fg",
                    className,
                )}
                {...props}
            />
        );
    },
    CodeHeader,
});
