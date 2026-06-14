import { defineToolkit } from "@assistant-ui/react";
import { AskUserTool } from "./ask-user-tool";
import { FileMutationTool } from "./file-mutation-tool";

export const toolkit = defineToolkit({
  ask_user: {
    type: "backend",
    render: AskUserTool,
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
