import { describe, expect, it } from "vitest";

import type { NovaAgent } from "../types/nova";
import { agentDisplayName } from "./agent-display";

function agent(key: string, name: string): NovaAgent {
    return {
        key,
        name,
        description: "",
        model: "m",
        provider: "p",
        parents: [],
        created_at: 0,
        updated_at: 0,
        kind: "main",
        mode: "primary",
        editable_fields: [],
    };
}

describe("agentDisplayName", () => {
    const agents = [agent("main", "Nova"), agent("tutor", "教育专家·苏明启")];

    it("uses the agents-table name for the bound key", () => {
        expect(agentDisplayName(agents, "main")).toBe("Nova");
        expect(agentDisplayName(agents, "tutor")).toBe("教育专家·苏明启");
    });

    it("falls back to the raw key when the agent is unknown (e.g. deleted)", () => {
        expect(agentDisplayName(agents, "ghost")).toBe("ghost");
    });

    it("falls back to the default when no key is known yet", () => {
        expect(agentDisplayName(agents, null)).toBe("Nova");
        expect(agentDisplayName(agents, undefined)).toBe("Nova");
        expect(agentDisplayName(agents, "")).toBe("Nova");
    });

    it("honours a custom fallback", () => {
        expect(agentDisplayName(agents, null, "Assistant")).toBe("Assistant");
    });

    it("uses the key when the agent has an empty name", () => {
        expect(agentDisplayName([agent("x", "")], "x")).toBe("x");
    });
});
