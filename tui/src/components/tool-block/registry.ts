import { shellRenderer, codeRunRenderer } from "./renderers/shell.ts";
import { readRenderer, readImageRenderer, writeRenderer, editRenderer } from "./renderers/file.ts";
import { globRenderer, grepRenderer } from "./renderers/search.ts";
import { webSearchRenderer, webFetchRenderer } from "./renderers/web.ts";
import { todoRenderer } from "./renderers/todo.ts";
import { SIMPLE_RENDERERS } from "./renderers/simple.ts";
import { createFallbackRenderer } from "./renderers/fallback.ts";
import type { ToolRenderer } from "./types.ts";

const RENDERERS: Record<string, ToolRenderer<any>> = {
    shell: shellRenderer,
    code_run: codeRunRenderer,
    read: readRenderer,
    read_image: readImageRenderer,
    write: writeRenderer,
    edit: editRenderer,
    glob: globRenderer,
    grep: grepRenderer,
    web_search: webSearchRenderer,
    web_fetch: webFetchRenderer,
    todo_write: todoRenderer,
    ...SIMPLE_RENDERERS,
};

export function getRenderer(toolName: string): ToolRenderer {
    return RENDERERS[toolName] ?? createFallbackRenderer(toolName);
}
