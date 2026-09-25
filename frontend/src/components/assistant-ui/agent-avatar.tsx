/**
 * Agent identity avatar: a colored rounded square with the agent's initial,
 * keyed by `agent.key` so the same agent always gets the same color. Shared by
 * the composer's agent chip/picker and the assistant message header.
 */

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

const SIZE_CLASS = {
    sm: "size-[18px] rounded-[5.5px] text-[11px]",
    md: "size-7 rounded-[9px] text-[13px]",
    lg: "size-6 rounded-[7px] text-[12px]",
} as const;

export function AgentAvatar({
    agentKey,
    name,
    size = "sm",
}: {
    agentKey: string;
    name: string;
    size?: keyof typeof SIZE_CLASS;
}) {
    const color = agentAvatarColor(agentKey || name || "?");
    const initial = (name || agentKey || "?").trim().charAt(0) || "?";
    return (
        <span
            aria-hidden
            className={`inline-flex shrink-0 items-center justify-center font-bold leading-none text-white ${SIZE_CLASS[size]}`}
            style={{ backgroundColor: color, borderColor: color }}
        >
            {initial}
        </span>
    );
}
