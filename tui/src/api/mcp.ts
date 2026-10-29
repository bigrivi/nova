/** MCP servers as the backend reports them: what loaded, what did not, and why. */
import { type JsonResponse, jsonInit, request } from "./client.ts";
import type { NovaMcpServer } from "./types.ts";

/** Every configured server, with the tool list an agent actually got. */
export async function listMcpServers(): Promise<NovaMcpServer[]> {
    const payload = await request<JsonResponse<NovaMcpServer>>("/api/mcp-servers");
    return payload.items;
}

/**
 * Remove a server from the config and reload the rest.
 *
 * The response is the refreshed list, so the caller does not have to refetch to
 * see the server disappear.
 */
export async function deleteMcpServer(name: string): Promise<NovaMcpServer[]> {
    const payload = await request<JsonResponse<NovaMcpServer>>(
        "/api/config/mcp/delete",
        jsonInit("POST", { name }),
    );
    return payload.items;
}
