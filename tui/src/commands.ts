/** Slash command table (ported from DEFAULT_COMMAND_SPECS in nova/cli/commands.py) */
export type CommandSpec = {
    id: string;
    label: string;
    description: string;
    usage: string;
    aliases: string[];
};

export const COMMANDS: CommandSpec[] = [
    {
        id: "new",
        label: "New Session",
        description: "Start a new conversation",
        usage: "/new",
        aliases: ["n"],
    },
    {
        id: "sessions",
        label: "Sessions",
        description: "Browse and load sessions",
        usage: "/sessions",
        aliases: ["ls"],
    },
    {
        id: "clear",
        label: "Clear",
        description: "Clear the screen",
        usage: "/clear",
        aliases: [],
    },
    {
        id: "models",
        label: "Models",
        description: "Show available models",
        usage: "/models",
        aliases: [],
    },
    {
        id: "variants",
        label: "Variants",
        description: "Browse and switch reasoning effort levels",
        usage: "/variants",
        aliases: [],
    },
    {
        id: "themes",
        label: "Themes",
        description: "Browse and switch UI themes",
        usage: "/themes",
        aliases: [],
    },
    {
        id: "permissions",
        label: "Permissions",
        description: "Show the permission mode and rules in force",
        usage: "/permissions",
        aliases: ["perms"],
    },
    {
        id: "rewind",
        label: "Rewind",
        description: "Undo a turn's file changes and drop the turns after it",
        usage: "/rewind",
        aliases: ["undo"],
    },
    {
        id: "tasks",
        label: "Tasks",
        description: "Show and cancel background tasks",
        usage: "/tasks",
        aliases: ["bg"],
    },
    {
        id: "review",
        label: "Review",
        description: "Ask the model to review the uncommitted diff",
        usage: "/review",
        aliases: [],
    },
    {
        id: "commit",
        label: "Commit",
        description: "Commit this session's changes after showing the message",
        usage: "/commit",
        aliases: [],
    },
    {
        id: "diff",
        label: "Diff",
        description: "Show what this session changed in git",
        usage: "/diff",
        aliases: ["changes"],
    },
    {
        id: "mcp",
        label: "MCP",
        description: "Show MCP servers and the tools they loaded",
        usage: "/mcp",
        aliases: [],
    },
    {
        id: "memory",
        label: "Memory",
        description: "Show and delete stored memories",
        usage: "/memory",
        aliases: ["memories"],
    },
    {
        id: "fork",
        label: "Fork",
        description: "Copy this conversation into a new session and switch to it",
        usage: "/fork",
        aliases: ["branch"],
    },
    {
        id: "compact",
        label: "Compact",
        description: "Summarise the history now to free context",
        usage: "/compact",
        aliases: [],
    },
    {
        id: "install-skill",
        label: "Install Skill",
        description: "Install or update a skill from ClawHub",
        usage: "/install-skill",
        aliases: [],
    },
    {
        id: "quit",
        label: "Quit",
        description: "Exit the application",
        usage: "/quit",
        aliases: ["q", "exit"],
    },
    {
        id: "agents",
        label: "Agents",
        description: "Browse and switch the active agent",
        usage: "/agents",
        aliases: [],
    },
    {
        id: "create-agent",
        label: "Create Agent",
        description: "Create a new agent",
        usage: "/create-agent",
        aliases: [],
    },
    {
        id: "delete-agent",
        label: "Delete Agent",
        description: "Delete an agent",
        usage: "/delete-agent",
        aliases: [],
    },
    {
        id: "install-global-skill",
        label: "Install Global Skill",
        description: "Install a skill globally",
        usage: "/install-global-skill",
        aliases: [],
    },
];

/** Match commands by prefix (including aliases); an empty prefix returns no matches */
export function matchCommands(partial: string): CommandSpec[] {
    const text = partial.trim().toLowerCase();
    if (!text) return [];
    return COMMANDS.filter(
        (cmd) =>
            cmd.usage.toLowerCase().startsWith(text) ||
            cmd.aliases.some((a) => a.startsWith(text.replace(/^\//, ""))),
    );
}

/** Parse a full command input: /cmd args → { id, args }; returns null for non-commands */
export function parseCommand(
    input: string,
): { id: string; args: string } | null {
    if (!input.startsWith("/")) return null;
    const [raw, ...rest] = input.trim().slice(1).split(/\s+/);
    if (!raw) return null;
    return { id: raw.toLowerCase(), args: rest.join(" ") };
}
