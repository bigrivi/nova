import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import type { NovaAgent } from "../../types/nova";
import { AgentAvatar } from "./agent-avatar";

/**
 * The composer's `@` sub-agent list. A plain absolutely-positioned panel — the
 * composer box is already `relative`, so no popover layer is warranted.
 */
export function SubagentMentionPicker({
    agents,
    activeIndex,
    onActiveIndexChange,
    onSelect,
}: {
    agents: NovaAgent[];
    activeIndex: number;
    onActiveIndexChange: (index: number) => void;
    onSelect: (agent: NovaAgent) => void;
}) {
    const { t } = useTranslation();
    const activeRef = useRef<HTMLDivElement | null>(null);

    // Keyboard navigation moves the highlight past the visible rows; keep the
    // active one in view. `nearest` keeps this from scrolling the page itself.
    useEffect(() => {
        activeRef.current?.scrollIntoView({ block: "nearest" });
    }, [activeIndex]);

    return (
        <div
            role="listbox"
            aria-label={t("composer.subagentMentionTitle")}
            className="absolute inset-x-0 bottom-full z-30 mb-1 max-h-60 overflow-y-auto rounded-xl border border-border bg-popover p-1 shadow-md"
        >
            <div className="px-2 py-1 text-[11px] font-medium text-muted-foreground">
                {t("composer.subagentMentionTitle")}
            </div>
            {agents.length === 0 ? (
                <div className="px-2 py-1.5 text-xs text-muted-foreground">
                    {t("composer.subagentMentionEmpty")}
                </div>
            ) : (
                agents.map((agent, index) => (
                    <div
                        key={agent.key}
                        ref={index === activeIndex ? activeRef : undefined}
                        role="option"
                        aria-selected={index === activeIndex}
                        onMouseDown={(event) => event.preventDefault()}
                        onMouseEnter={() => onActiveIndexChange(index)}
                        onClick={() => onSelect(agent)}
                        className={`flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1.5 text-left ${
                            index === activeIndex ? "bg-accent" : ""
                        }`}
                    >
                        <AgentAvatar
                            agentKey={agent.key}
                            name={agent.name || agent.key}
                            size="md"
                        />
                        <span className="flex min-w-0 flex-col">
                            <span className="truncate text-sm font-medium">
                                {agent.name || agent.key}
                            </span>
                            <span className="truncate text-xs text-muted-foreground">
                                {agent.description || `@${agent.key}`}
                            </span>
                        </span>
                    </div>
                ))
            )}
        </div>
    );
}
