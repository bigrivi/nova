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
        id: "theme",
        label: "Theme",
        description: "View or switch UI theme",
        usage: "/theme",
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
        id: "list-agents",
        label: "List Agents",
        description: "List all available agents",
        usage: "/list-agents",
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
