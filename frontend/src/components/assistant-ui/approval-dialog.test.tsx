// @vitest-environment jsdom
//
// The two approval cards from the spec: a shell run and a directory grant.
// The directory block names the backend `family` (the scope remembering
// would cover), never the single target file path.

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import type { ApprovalPending } from "../../stores/approval-store";
import { useApprovalStore } from "../../stores/approval-store";
import { ApprovalDialog, approvalDirVerbKey } from "./approval-dialog";

vi.mock("react-i18next", async (importOriginal) => {
    const actual = await importOriginal<typeof import("react-i18next")>();
    return {
        ...actual,
        useTranslation: () => ({ t: i18n.t.bind(i18n), i18n }),
    };
});

const base: ApprovalPending = {
    sessionId: "s-1",
    requestId: "r-1",
    command: "",
    description: "",
    toolName: "",
    rememberable: true,
    family: "",
    scriptScoped: false,
    dangerous: false,
    workspace: "",
    target: "",
};

beforeAll(async () => {
    await i18n.changeLanguage("zh-CN");
});

beforeEach(() => {
    cleanup();
    useApprovalStore.setState({ pending: null, pendingBySession: {} });
});

afterEach(() => {
    cleanup();
});

function show(pending: Partial<ApprovalPending>) {
    useApprovalStore.setState({
        pending: { ...base, ...pending },
        pendingBySession: {},
    });
    render(<ApprovalDialog />);
}

describe("approvalDirVerbKey", () => {
    it("maps writes and reads, case-insensitively", () => {
        expect(approvalDirVerbKey("write")).toBe("approval.verbWrite");
        expect(approvalDirVerbKey("edit")).toBe("approval.verbWrite");
        expect(approvalDirVerbKey("read")).toBe("approval.verbRead");
        expect(approvalDirVerbKey("Read_Image")).toBe("approval.verbRead");
        expect(approvalDirVerbKey("grep")).toBe("approval.verbRead");
        expect(approvalDirVerbKey("glob")).toBe("approval.verbRead");
    });

    it("leaves verbless tools on the legacy copy", () => {
        expect(approvalDirVerbKey("web_fetch")).toBeNull();
        expect(approvalDirVerbKey("")).toBeNull();
    });
});

describe("ApprovalDialog", () => {
    it("renders the shell card with the command and no workspace line", () => {
        show({
            toolName: "",
            command: "git status --short",
            workspace: "/Users/demo/project",
        });

        expect(screen.getByText("需要执行以下命令")).toBeTruthy();
        expect(screen.getByText("git status --short")).toBeTruthy();
        expect(screen.queryByText(/工作目录/)).toBeNull();
        expect(
            screen.getByText(
                "批准:仅本次执行。批准并记住:本会话内,同一类命令将不再询问。",
            ),
        ).toBeTruthy();
    });

    it("never renders the workspace line even when a workspace is active", () => {
        show({ toolName: "shell", command: "ls", workspace: "/Users/demo/project" });

        expect(screen.queryByText(/工作目录/)).toBeNull();
    });

    it("renders the directory card from the family, not the target", () => {
        show({
            toolName: "write",
            family: "/private/tmp/test_remember_dir",
            target: "/private/tmp/test_remember_dir/file.txt",
            workspace: "",
        });

        expect(screen.getByText("需要写入以下目录中的文件")).toBeTruthy();
        expect(
            screen.getByText("/private/tmp/test_remember_dir"),
        ).toBeTruthy();
        expect(
            screen.queryByText("/private/tmp/test_remember_dir/file.txt"),
        ).toBeNull();
        expect(
            screen.getByText(
                "批准:仅本次写入。批准并记住:本会话内,该目录及其子目录下的写入将不再询问。",
            ),
        ).toBeTruthy();
    });

    it("uses the read verb for read tools", () => {
        show({ toolName: "read", family: "/tmp/logs", workspace: "" });

        expect(screen.getByText("需要读取以下目录中的文件")).toBeTruthy();
        expect(
            screen.getByText(
                "批准:仅本次读取。批准并记住:本会话内,该目录及其子目录下的读取将不再询问。",
            ),
        ).toBeTruthy();
    });

    it("titles the file shape with needFileAccess, not the directory", () => {
        show({
            toolName: "read",
            family: "",
            target: "/private/tmp/test_remember_dir/.env",
            rememberable: false,
            workspace: "",
        });

        expect(screen.getByText("需要读取以下文件")).toBeTruthy();
        expect(
            screen.getByText("/private/tmp/test_remember_dir/.env"),
        ).toBeTruthy();
    });

    it("titles grep/glob with needSearch since they search a directory", () => {
        show({
            toolName: "grep",
            family: "",
            target: "/Users/demo/.ssh",
            rememberable: false,
            workspace: "",
        });

        expect(screen.getByText("需要在以下目录中搜索")).toBeTruthy();
        expect(screen.getByText("/Users/demo/.ssh")).toBeTruthy();
    });

    it("hides the explainer and the remember button when shell is unrememberable", () => {
        show({
            toolName: "shell",
            command: "rm -rf /tmp/x",
            rememberable: false,
        });

        expect(screen.getByText("需要执行以下命令")).toBeTruthy();
        expect(screen.getByText("批准")).toBeTruthy();
        expect(screen.getByText("拒绝")).toBeTruthy();
        expect(screen.queryByText("批准并记住")).toBeNull();
        expect(screen.queryByText(/批准:/)).toBeNull();
    });

    it("keeps the legacy copy for verbless tools", () => {
        show({
            toolName: "web_fetch",
            description: "Fetch a URL",
            target: "https://example.com",
        });

        expect(screen.getByText("工具调用：web_fetch")).toBeTruthy();
        expect(screen.queryByText(/需要/)).toBeNull();
        expect(screen.queryByText(/批准:/)).toBeNull();
    });

    it("renders the red card only for a dangerous shell approval", () => {
        show({
            toolName: "shell",
            command: "rm -rf /tmp/x",
            dangerous: true,
        });

        expect(
            document.querySelector('[data-dangerous="true"]'),
        ).toBeTruthy();
        // Copy is unchanged: the color carries the danger, not new wording.
        expect(screen.getByText("需要执行以下命令")).toBeTruthy();
        expect(
            screen.getByText(
                "批准:仅本次执行。批准并记住:本会话内,同一类命令将不再询问。",
            ),
        ).toBeTruthy();
        // Remember stays: a dangerous command can still be granted.
        expect(screen.getByText("批准并记住")).toBeTruthy();
        cleanup();

        show({ toolName: "shell", command: "ls" });
        expect(
            document.querySelector('[data-dangerous="true"]'),
        ).toBeNull();
    });

    it("never renders red for a non-shell card", () => {
        show({
            toolName: "write",
            family: "/private/tmp/test_remember_dir",
            target: "/private/tmp/test_remember_dir/file.txt",
            dangerous: true,
        });

        expect(
            document.querySelector('[data-dangerous="true"]'),
        ).toBeNull();
    });
});
