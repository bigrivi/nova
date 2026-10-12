import type {
    McpKeyValue,
    McpTransportKind,
    NovaMcpServerInput,
    NovaMcpServerRecord,
} from "../../../types/nova";

export type {
    McpKeyValue,
    McpTransportKind,
    NovaMcpServerInput,
    NovaMcpServerRecord,
};

/**
 * The server form's state, in the shape the user thinks in: a name, a way to
 * reach the server, and the parts belonging to that way.
 */
export type McpFormState = {
    name: string;
    transport: McpTransportKind;
    command: string;
    /** One argument per row; blanks are dropped on submit. */
    args: string[];
    env: McpKeyValue[];
    url: string;
    headers: McpKeyValue[];
};

export const TRANSPORT_VALUES: readonly McpTransportKind[] = [
    "stdio",
    "http",
];

export function defaultFormState(): McpFormState {
    return {
        name: "",
        transport: "stdio",
        command: "",
        args: [],
        env: [],
        url: "",
        headers: [],
    };
}

/**
 * Seed the form from a stored server.
 *
 * `env` and `headers` come back as key *names* only -- the API withholds the
 * values -- so each becomes a row with an empty value. The server reads an empty
 * value as "keep what you have", so opening the form and saving it unchanged
 * leaves every secret intact. To rotate one, type over it; to remove one, delete
 * its row.
 */
export function formStateFromRecord(
    record: NovaMcpServerRecord | undefined,
): McpFormState {
    if (!record) {
        return defaultFormState();
    }
    return {
        name: record.name,
        transport: record.transport,
        command: record.command,
        args: record.args.length > 0 ? [...record.args] : [""],
        env: record.env_keys.map((key) => ({ key, value: "" })),
        url: record.url,
        headers: record.header_keys.map((key) => ({ key, value: "" })),
    };
}

/**
 * The payload the API takes. Row keys are trimmed and blank rows dropped, so a
 * half-typed row the user abandoned does not become an env var named "".
 */
export function toInput(state: McpFormState): NovaMcpServerInput {
    return {
        name: state.name.trim(),
        command:
            state.transport === "stdio" ? state.command.trim() : "",
        args:
            state.transport === "stdio"
                ? state.args.map((arg) => arg.trim()).filter((arg) => arg !== "")
                : [],
        env:
            state.transport === "stdio"
                ? state.env
                      .map((row) => ({ key: row.key.trim(), value: row.value }))
                      .filter((row) => row.key !== "")
                : [],
        url: state.transport === "http" ? state.url.trim() : "",
        headers:
            state.transport === "http"
                ? state.headers
                      .map((row) => ({ key: row.key.trim(), value: row.value }))
                      .filter((row) => row.key !== "")
                : [],
    };
}

/** Whether the form holds enough to be worth testing. */
export function isTestable(state: McpFormState): boolean {
    return state.transport === "stdio"
        ? state.command.trim() !== ""
        : state.url.trim() !== "";
}

export const inputClassName =
    "h-9 w-full rounded-lg border bg-background px-3 text-base outline-none focus:border-ring focus:ring-2 focus:ring-ring/20 sm:text-sm";

/** The human-readable target of a server, for the list row. */
export function serverTarget(record: NovaMcpServerRecord): string {
    if (record.transport === "http") {
        return record.url;
    }
    const args = record.args.join(" ");
    return args ? `${record.command} ${args}` : record.command;
}