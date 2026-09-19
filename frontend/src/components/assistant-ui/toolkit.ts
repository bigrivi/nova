import { defineToolkit } from "@assistant-ui/react";
import { AskUserTool } from "./ask-user-tool";
import { DelegateTool } from "./delegate-tool";
import { FileMutationTool } from "./file-mutation-tool";

export const toolkit = defineToolkit({
    ask_user: {
        type: "backend",
        render: AskUserTool,
    },
    delegate_to_agent: {
        type: "backend",
        render: DelegateTool,
    },
    edit: {
        type: "backend",
        render: FileMutationTool,
    },
    write: {
        type: "backend",
        render: FileMutationTool,
    },
});
