/** tree-sitter extra parser registration: register the default parser list before OpenTUI worker initialization */
import { addDefaultParsers } from "@opentui/core";
import { existsSync } from "node:fs";
import { join } from "node:path";

const ASSETS_DIR = join(import.meta.dir, "..", "assets", "tree-sitter");
const WASMS_DIR = join(
    import.meta.dir,
    "..",
    "node_modules",
    "tree-sitter-wasms",
    "out",
);

const EXTRA_PARSERS = [
    {
        filetype: "python",
        aliases: ["py", "python3"],
        wasm: join(WASMS_DIR, "tree-sitter-python.wasm"),
        queries: {
            highlights: [join(ASSETS_DIR, "python-highlights.scm")],
        },
    },
];

export function registerExtraParsers(): void {
    const available = EXTRA_PARSERS.filter((parser) => existsSync(parser.wasm));
    if (available.length > 0) {
        addDefaultParsers(available);
    }
}
