/** Row text for the MCP panel.
 *
 *  The whole point of the panel is answering "why did that tool disappear", so
 *  the three states it must never blur are: not loaded yet, loaded nothing, and
 *  failed to connect.
 */
import type { NovaMcpServer } from "../api/types.ts";

export type McpState = "failed" | "empty" | "pending" | "ready";

/** Which of the four situations a server is in. */
export function mcpState(server: NovaMcpServer): McpState {
    if (server.error) return "failed";
    if (server.loaded_tools === null) return "pending";
    if (server.loaded_tools.length === 0) return "empty";
    return "ready";
}

/** Status word with the glyph that survives a narrow terminal. */
export function mcpStatusLabel(server: NovaMcpServer): string {
    const state = mcpState(server);
    if (state === "failed") return "✗ failed";
    if (state === "empty") return "○ no tools";
    if (state === "pending") return "… not loaded";
    return "● ready";
}

/** `12 tools` for a loaded server, and the reason when it is short of tools. */
export function mcpToolSummary(server: NovaMcpServer): string {
    const loaded = server.loaded_tools?.length ?? 0;
    const skipped = server.skipped_tools?.length ?? 0;
    if (mcpState(server) === "pending") return "not loaded yet";
    if (mcpState(server) === "failed") return server.error ?? "failed to connect";
    if (loaded === 0) return "connected, no tools offered";
    return skipped > 0 ? `${loaded} tools, ${skipped} blocked` : `${loaded} tools`;
}

/** How the server is reached: the command for stdio, the URL for http. */
export function mcpTransportLine(server: NovaMcpServer): string {
    if (server.transport === "http") return `http  ${server.url}`;
    const args = server.args.length > 0 ? ` ${server.args.join(" ")}` : "";
    return `stdio  ${server.command}${args}`;
}

/** One list line: status, name, and the tool summary. */
export function mcpLine(server: NovaMcpServer): string {
    return `${mcpStatusLabel(server)}  ${server.name}  ·  ${mcpToolSummary(server)}`;
}
