/** Text lines for the read-only permissions panel.
 *
 *  Kept out of the component so the wording can be tested without a renderer:
 *  what a user reads here is the only explanation they get for why a command
 *  was asked, refused, or let through.
 */
import type { NovaPermissionPolicy } from "../api/types.ts";
import {
    MODE_LABEL,
    MODE_SUMMARY,
    type PermissionMode,
} from "../stores/permission-store.ts";

const MAX_ITEMS = 4;

/** `a, b, c` with the remainder counted rather than listed. */
export function joinLimited(values: string[], max = MAX_ITEMS): string {
    if (values.length === 0) return "none";
    const shown = values.slice(0, max).join(", ");
    const rest = values.length - max;
    return rest > 0 ? `${shown} +${rest} more` : shown;
}

/** Every line of the panel, in display order. */
export function policyLines(
    policy: NovaPermissionPolicy | null,
    mode: PermissionMode,
): string[] {
    const lines = [`mode        ${MODE_LABEL[mode]} — ${MODE_SUMMARY[mode]}`];
    if (!policy) {
        lines.push("config      loading…");
        return lines;
    }

    lines.push(
        policy.configured
            ? `config      ${policy.path}`
            : `config      ${policy.path} (absent: built-in defaults apply)`,
    );
    lines.push(
        `read outside ${policy.block_reads_outside_workspace ? "blocked" : "asks when a path leaves the workspace"}`,
    );
    lines.push(
        `shell allow ${policy.shell_allow.length}  ${joinLimited(policy.shell_allow)}`,
    );
    lines.push(
        `shell ask   ${policy.shell_ask.length}  ${joinLimited(
            policy.shell_ask.map((rule) => rule.description || rule.match),
        )}`,
    );
    lines.push(
        `switched off ${policy.shell_disable.length}  ${joinLimited(policy.shell_disable)}`,
    );
    lines.push(
        `tools       ${joinLimited(
            policy.tools.map((tool) => `${tool.name}=${tool.effect}`),
        )}`,
    );
    return lines;
}
