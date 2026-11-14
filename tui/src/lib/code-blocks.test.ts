import { describe, expect, test } from "bun:test";
import { extractCodeBlocks } from "./code-blocks.ts";

describe("extractCodeBlocks", () => {
    test("returns the code without the fence or the language tag", () => {
        const text = "before\n```ts\nconst a = 1;\n```\nafter";
        expect(extractCodeBlocks(text)).toEqual(["const a = 1;"]);
    });

    test("finds every block in order", () => {
        const text = "```\none\n```\ntext\n```py\ntwo\n```";
        expect(extractCodeBlocks(text)).toEqual(["one", "two"]);
    });

    test("an unterminated fence is not a block", () => {
        expect(extractCodeBlocks("```ts\nconst a = 1;")).toEqual([]);
    });

    test("a message with no fence has no blocks", () => {
        expect(extractCodeBlocks("just prose")).toEqual([]);
    });

    test("does not leak state between calls", () => {
        // A global regex keeps lastIndex; a call after a failed match must
        // still start from the beginning.
        expect(extractCodeBlocks("no blocks")).toEqual([]);
        expect(extractCodeBlocks("```\none\n```")).toEqual(["one"]);
    });
});
