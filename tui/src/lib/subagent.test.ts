import { describe, expect, test } from "bun:test";
import { parseSubagentNotice } from "./subagent.ts";

describe("parseSubagentNotice", () => {
    test("parses a done report", () => {
        expect(
            parseSubagentNotice("[subagent:explorer status=done]\nbody"),
        ).toEqual({ target: "explorer", status: "done" });
    });

    test("parses an error report", () => {
        expect(
            parseSubagentNotice("[subagent:explorer status=error]\nboom"),
        ).toEqual({ target: "explorer", status: "error" });
    });

    test("ignores the body", () => {
        const notice = parseSubagentNotice(
            "[subagent:coder status=done]\nline one\nline two",
        );
        expect(notice).toEqual({ target: "coder", status: "done" });
    });

    test("rejects a missing target", () => {
        expect(parseSubagentNotice("[subagent: status=done]\nx")).toBeNull();
    });

    test("rejects ordinary text", () => {
        expect(parseSubagentNotice("hello")).toBeNull();
    });

    test("rejects a header that is not at the start", () => {
        expect(
            parseSubagentNotice("prefix [subagent:explorer status=done]"),
        ).toBeNull();
    });
});
