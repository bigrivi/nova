/** Dialog title, target block and remember-scope copy for an approval. */
import type { ApprovalPending } from "../stores/approval-store.ts";

const DIR_VERBS: Record<string, "read" | "write"> = {
    write: "write",
    edit: "write",
    read: "read",
    read_image: "read",
    grep: "read",
    glob: "read",
};

export function approvalCopy(pending: ApprovalPending): {
    title: string;
    block: string;
    scope: string;
} {
    const toolName = pending.toolName.trim().toLowerCase();
    const isShell = !toolName || toolName === "shell";
    const isSearch = toolName === "grep" || toolName === "glob";
    const verb = DIR_VERBS[toolName];
    const isDir = verb !== undefined;

    const title = isShell
        ? "Needs to run the following command"
        : isSearch
          ? "Needs to search in the following directory"
          : !isDir
            ? `Tool call: ${pending.toolName}`
            : pending.family
              ? `Needs to ${verb} files in the following directory`
              : `Needs to ${verb} the following file`;

    const block = isShell
        ? pending.command
        : isDir
          ? pending.family || pending.target
          : "";

    const scope = isShell
        ? pending.rememberable
            ? "Approve: just this run. Approve & remember: commands of the same kind won't ask again this session."
            : ""
        : isDir
          ? `Approve: just this ${verb}. Approve & remember: ${verb}s under this directory and its subdirectories won't ask again this session.`
          : "";

    return { title, block, scope };
}