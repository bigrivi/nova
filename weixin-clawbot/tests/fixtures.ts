/**
 * Shared test fixtures.
 *
 * The agent list a fake Nova reports. Only primary agents appear: that is what
 * `listAgents` returns, so a fake that offered a sub-agent would test a state
 * the client never produces.
 */

import type { NovaAgentSummary } from "../src/nova.js";

/** The agents `/agent` may switch between. */
export const PRIMARY_AGENTS: readonly NovaAgentSummary[] = [
  {
    key: "main",
    name: "Nova",
    mode: "primary",
    posture: null,
    provider: "anthropic",
    model: "claude-sonnet-4",
    // No agent configures one, which is what makes the default the interesting
    // case rather than the exception.
    workspaceDir: null,
  },
  {
    key: "writing-coach",
    name: "写作教练",
    mode: "primary",
    posture: null,
    provider: "anthropic",
    model: "claude-sonnet-4",
    workspaceDir: null,
  },
];

/** An agent key that must never be switchable to, because it is a subagent. */
export const SUBAGENT_KEY = "researcher";
