import { describe, expect, test } from "bun:test";
import type { NovaMcpServer } from "../api/types.ts";
import { mcpLine, mcpState, mcpToolSummary, mcpTransportLine } from "./mcp-format.ts";

function server(overrides: Partial<NovaMcpServer> = {}): NovaMcpServer {
    return {
        name: "github",
        transport: "stdio",
        command: "npx",
        args: ["-y", "server-github"],
        url: "",
        env_keys: [],
        header_keys: [],
        loaded_tools: ["github__search", "github__create_issue"],
        skipped_tools: [],
        error: null,
        ...overrides,
    };
}

describe("mcpState", () => {
    test("distinguishes the four situations", () => {
        expect(mcpState(server())).toBe("ready");
        expect(mcpState(server({ error: "boom" }))).toBe("failed");
        expect(mcpState(server({ loaded_tools: null }))).toBe("pending");
        expect(mcpState(server({ loaded_tools: [] }))).toBe("empty");
    });
});

describe("mcpToolSummary", () => {
    test("counts tools and blocked ones", () => {
        expect(mcpToolSummary(server())).toBe("2 tools");
        expect(
            mcpToolSummary(
                server({ skipped_tools: [{ tool: "x", reason: "denied" }] }),
            ),
        ).toBe("2 tools, 1 blocked");
    });

    test("never reports zero for a server that has not loaded", () => {
        expect(mcpToolSummary(server({ loaded_tools: null }))).toBe(
            "not loaded yet",
        );
        expect(mcpToolSummary(server({ loaded_tools: [] }))).toBe(
            "connected, no tools offered",
        );
    });

    test("shows the connection error instead of a count", () => {
        expect(mcpToolSummary(server({ error: "ECONNREFUSED" }))).toBe(
            "ECONNREFUSED",
        );
    });
});

describe("mcpTransportLine", () => {
    test("renders stdio as the command and args", () => {
        expect(mcpTransportLine(server())).toBe("stdio  npx -y server-github");
    });

    test("renders http as the url", () => {
        expect(
            mcpTransportLine(
                server({ transport: "http", url: "https://mcp.example/sse" }),
            ),
        ).toBe("http  https://mcp.example/sse");
    });
});

describe("mcpLine", () => {
    test("leads with the status", () => {
        const line = mcpLine(server());
        expect(line).toContain("ready");
        expect(line).toContain("github");
        expect(line).toContain("2 tools");
    });
});
