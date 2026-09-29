/**
 * Agent identity avatar, shared by the composer's agent chip/picker and the
 * assistant message header so the two can never drift apart.
 *
 * The default Nova agent is a product, not a person: it gets the branded bot
 * glyph on a bordered roundel. The border matters — the composer chip tints
 * its own background with the same brand-soft, so an unbordered fill would
 * dissolve into the chip and read as loose text. Named agents get a colored
 * rounded square with their initial, keyed by `agent.key`.
 */
import { BotIcon } from "lucide-react";

import { DEFAULT_AGENT_KEY } from "@/lib/nova-constants";

const AVATAR_PALETTE = [
    "#1D5FA8",
    "#6D4AA0",
    "#0E7C6B",
    "#B0562A",
    "#A8325A",
    "#4A6B2A",
    "#8A6D1B",
    "#3A6EA5",
];

function agentAvatarColor(key: string): string {
    let hash = 0;
    for (let i = 0; i < key.length; i += 1) {
        hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
    }
    return AVATAR_PALETTE[hash % AVATAR_PALETTE.length];
}

type AvatarSize = "sm" | "md" | "lg";

const SIZE_CLASS: Record<AvatarSize, string> = {
    sm: "size-[18px]",
    md: "size-7",
    lg: "size-6",
};

/** Shape and type scale for the initial; the bot roundel needs neither. */
const INITIAL_CLASS: Record<AvatarSize, string> = {
    sm: "rounded-[5.5px] text-[11px]",
    md: "rounded-[9px] text-[13px]",
    lg: "rounded-[7px] text-[12px]",
};

function isDefaultAgent(agentKey: string): boolean {
    return (
        !agentKey || agentKey === DEFAULT_AGENT_KEY || agentKey === "agent"
    );
}

export function AgentAvatar({
    agentKey,
    name,
    size = "sm",
}: {
    agentKey: string;
    name: string;
    size?: AvatarSize;
}) {
    if (isDefaultAgent(agentKey)) {
        return (
            <span
                aria-hidden
                className={`inline-flex shrink-0 items-center justify-center rounded-full border border-brand/40 bg-brand-soft text-brand shadow-sm ${SIZE_CLASS[size]}`}
            >
                <BotIcon className="size-3" />
            </span>
        );
    }
    const initial = (name || agentKey || "?").trim().charAt(0) || "?";
    const color = agentAvatarColor(agentKey || name || "?");
    return (
        <span
            aria-hidden
            className={`inline-flex shrink-0 items-center justify-center font-bold leading-none text-white ${SIZE_CLASS[size]} ${INITIAL_CLASS[size]}`}
            style={{ backgroundColor: color, borderColor: color }}
        >
            {initial}
        </span>
    );
}
