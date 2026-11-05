import { describe, expect, test } from "bun:test";

import { splitStreamingMarkdown } from "./streaming-markdown";

describe("streaming markdown split", () => {
    test("an empty stream has no blocks and an empty tail", () => {
        expect(splitStreamingMarkdown("")).toEqual({
            blocks: [],
            tail: { kind: "text", raw: "" },
        });
    });

    test("the first paragraph stays in the tail", () => {
        expect(splitStreamingMarkdown("Hello")).toEqual({
            blocks: [],
            tail: { kind: "text", raw: "Hello" },
        });
    });

    test("a blank line promotes the finished paragraph", () => {
        expect(splitStreamingMarkdown("Hello\n\nWorld")).toEqual({
            blocks: ["Hello"],
            tail: { kind: "text", raw: "World" },
        });
    });

    test("a trailing blank line leaves an empty tail", () => {
        expect(splitStreamingMarkdown("Hello\n\nWorld\n\n")).toEqual({
            blocks: ["Hello", "World"],
            tail: { kind: "text", raw: "" },
        });
    });

    test("leading blank lines do not become blocks", () => {
        expect(splitStreamingMarkdown("\n\nHello")).toEqual({
            blocks: [],
            tail: { kind: "text", raw: "Hello" },
        });
    });

    test("a closed fence is complete even without a following blank line", () => {
        expect(splitStreamingMarkdown("```ts\nconst a = 1\n```")).toEqual({
            blocks: ["```ts\nconst a = 1\n```"],
            tail: { kind: "text", raw: "" },
        });
    });

    test("an open fence becomes a code tail with its language", () => {
        expect(splitStreamingMarkdown("```ts\nconst a = 1")).toEqual({
            blocks: [],
            tail: {
                kind: "code",
                raw: "```ts\nconst a = 1",
                language: "ts",
            },
        });
    });

    test("a fence interrupting a paragraph closes the paragraph first", () => {
        expect(splitStreamingMarkdown("Here is code:\n```py\nprint(1)")).toEqual({
            blocks: ["Here is code:"],
            tail: {
                kind: "code",
                raw: "```py\nprint(1)",
                language: "py",
            },
        });
    });

    test("a closed fence followed by a paragraph promotes the fence", () => {
        expect(
            splitStreamingMarkdown("```ts\nx\n```\n\nAfter the block"),
        ).toEqual({
            blocks: ["```ts\nx\n```"],
            tail: { kind: "text", raw: "After the block" },
        });
    });

    test("tilde fences work and a shorter fence does not close a longer one", () => {
        expect(splitStreamingMarkdown("~~~js\nx\n~~~")).toEqual({
            blocks: ["~~~js\nx\n~~~"],
            tail: { kind: "text", raw: "" },
        });
        expect(splitStreamingMarkdown("````\nx\n```")).toEqual({
            blocks: [],
            tail: { kind: "code", raw: "````\nx\n```", language: null },
        });
    });

    test("blank lines inside a fence are content", () => {
        expect(splitStreamingMarkdown("```\na\n\nb\n```")).toEqual({
            blocks: ["```\na\n\nb\n```"],
            tail: { kind: "text", raw: "" },
        });
    });

    test("a tilde line does not close a backtick fence", () => {
        expect(splitStreamingMarkdown("```\na\n~~~~\nb\n```")).toEqual({
            blocks: ["```\na\n~~~~\nb\n```"],
            tail: { kind: "text", raw: "" },
        });
    });

    test("CRLF is normalised before scanning", () => {
        expect(splitStreamingMarkdown("a\r\n\r\nb")).toEqual({
            blocks: ["a"],
            tail: { kind: "text", raw: "b" },
        });
    });

    test("several finished blocks are kept in order", () => {
        expect(
            splitStreamingMarkdown("# Title\n\none\n\n- two\n\nthree"),
        ).toEqual({
            blocks: ["# Title", "one", "- two"],
            tail: { kind: "text", raw: "three" },
        });
    });
});
