// @vitest-environment jsdom
//
// SchedulesManagerContent, tested from the outside in: the rows users read and
// the buttons they press. The validation rules themselves belong to the form
// helpers (see lib/schedule.test.ts); these pin that the dialog surfaces them,
// sends only the active kind's fields, and never fires a request when local
// checks fail.

import {
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from "@testing-library/react";
import {
    afterEach,
    beforeAll,
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest";

import * as novaApi from "@/lib/nova-api";
import { useConversationStore } from "@/stores/conversation-store";
import { useScheduleStore } from "@/stores/schedule-store";
import type { NovaAgent, NovaScheduleJob } from "@/types/nova";
import i18n from "../../i18n";
import { SchedulesManagerContent } from "./schedules-manager-dialog";

vi.mock("@/lib/nova-api", () => ({
    listSchedules: vi.fn(),
    createSchedule: vi.fn(),
    updateSchedule: vi.fn(),
    deleteSchedule: vi.fn(),
    runScheduleNow: vi.fn(),
}));

vi.mock("react-i18next", async (importOriginal) => {
    const actual = await importOriginal<typeof import("react-i18next")>();
    return {
        ...actual,
        useTranslation: () => ({ t: i18n.t.bind(i18n), i18n }),
    };
});

const listSchedulesMock = vi.mocked(novaApi.listSchedules);
const createScheduleMock = vi.mocked(novaApi.createSchedule);
const updateScheduleMock = vi.mocked(novaApi.updateSchedule);
const deleteScheduleMock = vi.mocked(novaApi.deleteSchedule);
const runScheduleNowMock = vi.mocked(novaApi.runScheduleNow);

const agents: NovaAgent[] = [
    {
        key: "main",
        name: "主智能体",
        description: "",
        model: "m",
        provider: "p",
        parents: [],
        workspace_dir: null,
        created_at: 0,
        updated_at: 0,
        kind: "main",
        mode: "primary",
        editable_fields: [],
    },
];

function job(overrides: Partial<NovaScheduleJob> = {}): NovaScheduleJob {
    return {
        id: "job-1",
        name: "早报",
        prompt: "总结一下",
        kind: "cron",
        cron_expr: "0 9 * * *",
        interval_minutes: null,
        run_at: "",
        enabled: true,
        session_id: "s1",
        agent_key: "main",
        next_run_at: "2026-10-22T09:00:00+08:00",
        last_run_at: "2026-10-21T09:00:00+08:00",
        last_status: "failed",
        last_error: "boom",
        created_at: 1761000000,
        ...overrides,
    };
}

beforeAll(async () => {
    await i18n.changeLanguage("zh-CN");
    if (!Element.prototype.scrollIntoView) {
        Element.prototype.scrollIntoView = (() => {}) as unknown as Element["scrollIntoView"];
    }
});

beforeEach(() => {
    cleanup();
    vi.clearAllMocks();
    listSchedulesMock.mockResolvedValue([]);
    useScheduleStore.getState().reset();
    useConversationStore.setState({
        threads: [
            {
                id: "s1",
                title: "S1",
                status: "regular",
                workspace_dir: null,
                pinned: false,
                updated_at: 0,
                project_id: null,
                agent_key: "main",
            },
        ],
        currentThreadId: "s1",
    });
});

afterEach(() => {
    cleanup();
});

async function openCreate() {
    fireEvent.click(screen.getByText("新建任务"));
    await screen.findByText("新建定时任务");
}

function fillNameAndPrompt(name: string, prompt: string) {
    fireEvent.change(screen.getByLabelText("名称"), {
        target: { value: name },
    });
    fireEvent.change(screen.getByLabelText("任务描述"), {
        target: { value: prompt },
    });
}

describe("SchedulesManagerContent list", () => {
    it("renders the name, schedule line, next run, status badge and error", async () => {
        listSchedulesMock.mockResolvedValue([job()]);
        render(<SchedulesManagerContent agents={agents} />);

        await screen.findByText("早报");
        expect(screen.getByText("每天 9:00")).toBeTruthy();
        expect(document.body.textContent).toContain("下次：");
        expect(screen.getByText("失败")).toBeTruthy();
        expect(screen.getByText("boom")).toBeTruthy();
        expect(screen.getByText("总结一下")).toBeTruthy();
    });

    it("renders every last-status badge with its own label", async () => {
        listSchedulesMock.mockResolvedValue([
            job({ id: "r", name: "job-running", last_status: "running" }),
            job({ id: "s", name: "job-ok", last_status: "succeeded" }),
            job({ id: "f", name: "job-bad", last_status: "failed" }),
            job({ id: "k", name: "job-skip", last_status: "skipped" }),
            job({ id: "m", name: "job-miss", last_status: "missed" }),
        ]);
        render(<SchedulesManagerContent agents={agents} />);

        await screen.findByText("job-running");
        expect(screen.getByText("执行中")).toBeTruthy();
        expect(screen.getByText("成功")).toBeTruthy();
        expect(screen.getByText("失败")).toBeTruthy();
        expect(screen.getByText("跳过")).toBeTruthy();
        expect(screen.getByText("错过")).toBeTruthy();
    });
});

describe("SchedulesManagerContent create dialog", () => {
    it("swaps the schedule fields when the kind changes", async () => {
        render(<SchedulesManagerContent agents={agents} />);
        await openCreate();

        expect(screen.getByLabelText("Cron 表达式")).toBeTruthy();
        expect(screen.getByText("每 5 分钟")).toBeTruthy();
        expect(screen.queryByLabelText("每 N 分钟")).toBeNull();
        expect(screen.queryByLabelText("执行时间")).toBeNull();

        fireEvent.click(screen.getByText("间隔"));
        expect(screen.getByLabelText("每 N 分钟")).toBeTruthy();
        expect(screen.queryByLabelText("Cron 表达式")).toBeNull();
        expect(screen.queryByLabelText("执行时间")).toBeNull();

        fireEvent.click(screen.getByText("单次"));
        expect(screen.getByLabelText("执行时间")).toBeTruthy();
        expect(screen.queryByLabelText("Cron 表达式")).toBeNull();
        expect(screen.queryByLabelText("每 N 分钟")).toBeNull();
    });

    it("blocks an illegal cron without a request", async () => {
        render(<SchedulesManagerContent agents={agents} />);
        await openCreate();

        fillNameAndPrompt("早报", "总结");
        fireEvent.change(screen.getByLabelText("Cron 表达式"), {
            target: { value: "oops" },
        });
        fireEvent.click(screen.getByText("创建"));

        expect(
            await screen.findByText(
                "请输入 5 段式 cron 表达式，例如 0 9 * * *。",
            ),
        ).toBeTruthy();
        expect(createScheduleMock).not.toHaveBeenCalled();
    });

    it("blocks a zero interval without a request", async () => {
        render(<SchedulesManagerContent agents={agents} />);
        await openCreate();

        fireEvent.click(screen.getByText("间隔"));
        fillNameAndPrompt("巡检", "看看");
        fireEvent.change(screen.getByLabelText("每 N 分钟"), {
            target: { value: "0" },
        });
        fireEvent.click(screen.getByText("创建"));

        expect(
            await screen.findByText("请输入大于 0 的整数分钟数。"),
        ).toBeTruthy();
        expect(createScheduleMock).not.toHaveBeenCalled();
    });

    it("blocks an empty prompt without a request", async () => {
        render(<SchedulesManagerContent agents={agents} />);
        await openCreate();

        fireEvent.change(screen.getByLabelText("名称"), {
            target: { value: "早报" },
        });
        fireEvent.click(screen.getByText("创建"));

        expect(
            await screen.findByText("任务描述不能为空。"),
        ).toBeTruthy();
        expect(createScheduleMock).not.toHaveBeenCalled();
    });

    it("sends only the cron fields for a cron job", async () => {
        createScheduleMock.mockResolvedValue(job());
        render(<SchedulesManagerContent agents={agents} />);
        await openCreate();

        fillNameAndPrompt("早报", "每天总结");
        fireEvent.click(screen.getByText("创建"));

        await waitFor(() =>
            expect(createScheduleMock).toHaveBeenCalledTimes(1),
        );
        expect(createScheduleMock.mock.calls[0][0]).toEqual({
            name: "早报",
            prompt: "每天总结",
            kind: "cron",
            session_id: "s1",
            agent_key: "main",
            cron_expr: "0 9 * * *",
        });
    });

    it("sends minutes as a number for an interval job", async () => {
        createScheduleMock.mockResolvedValue(
            job({ kind: "interval", interval_minutes: 15 }),
        );
        render(<SchedulesManagerContent agents={agents} />);
        await openCreate();

        fireEvent.click(screen.getByText("间隔"));
        fillNameAndPrompt("巡检", "看看");
        fireEvent.change(screen.getByLabelText("每 N 分钟"), {
            target: { value: "15" },
        });
        fireEvent.click(screen.getByText("创建"));

        await waitFor(() =>
            expect(createScheduleMock).toHaveBeenCalledTimes(1),
        );
        expect(createScheduleMock.mock.calls[0][0]).toEqual({
            name: "巡检",
            prompt: "看看",
            kind: "interval",
            session_id: "s1",
            agent_key: "main",
            interval_minutes: 15,
        });
    });
});

describe("SchedulesManagerContent session select", () => {
    it("lists session titles with the current-session marker", async () => {
        useConversationStore.setState({
            threads: [
                {
                    id: "s1",
                    title: "S1",
                    status: "regular",
                    workspace_dir: null,
                    pinned: false,
                    updated_at: 0,
                    project_id: null,
                    agent_key: "main",
                },
                {
                    id: "s2",
                    title: "S2",
                    status: "regular",
                    workspace_dir: null,
                    pinned: false,
                    updated_at: 0,
                    project_id: null,
                    agent_key: "main",
                },
            ],
            currentThreadId: "s1",
        });
        render(<SchedulesManagerContent agents={agents} />);
        await openCreate();

        fireEvent.click(
            screen.getByRole("combobox", { name: "目标会话" }),
        );
        expect(
            await screen.findByRole("option", { name: "S1 s1 · 当前会话" }),
        ).toBeTruthy();
        expect(
            screen.getByRole("option", { name: "S2 s2" }),
        ).toBeTruthy();
    });

    it("sends the picked session id on create", async () => {
        useConversationStore.setState({
            threads: [
                {
                    id: "s1",
                    title: "S1",
                    status: "regular",
                    workspace_dir: null,
                    pinned: false,
                    updated_at: 0,
                    project_id: null,
                    agent_key: "main",
                },
                {
                    id: "s2",
                    title: "S2",
                    status: "regular",
                    workspace_dir: null,
                    pinned: false,
                    updated_at: 0,
                    project_id: null,
                    agent_key: "main",
                },
            ],
            currentThreadId: "s1",
        });
        createScheduleMock.mockResolvedValue(job({ session_id: "s2" }));
        render(<SchedulesManagerContent agents={agents} />);
        await openCreate();

        fillNameAndPrompt("早报", "每天总结");
        fireEvent.click(
            screen.getByRole("combobox", { name: "目标会话" }),
        );
        fireEvent.click(
            await screen.findByRole("option", { name: "S2 s2" }),
        );
        fireEvent.click(screen.getByText("创建"));

        await waitFor(() =>
            expect(createScheduleMock).toHaveBeenCalledTimes(1),
        );
        expect(createScheduleMock.mock.calls[0][0]).toMatchObject({
            session_id: "s2",
        });
    });

    it("keeps a deleted session visible when editing its job", async () => {
        listSchedulesMock.mockResolvedValue([
            job({ session_id: "gone-session-id-123" }),
        ]);
        render(<SchedulesManagerContent agents={agents} />);

        await screen.findByText("早报");
        expect(screen.getByText("会话不存在")).toBeTruthy();

        fireEvent.click(screen.getByLabelText("编辑"));
        await screen.findByText("编辑定时任务");

        const trigger = screen.getByRole("combobox", {
            name: "目标会话",
        });
        expect(trigger.textContent).toContain("会话不存在");
        fireEvent.click(trigger);
        expect(
            await screen.findByRole("option", {
                name: "gone-ses… · 会话不存在",
            }),
        ).toBeTruthy();
    });
});

describe("SchedulesManagerContent row actions", () => {
    it("toggles enabled through updateSchedule", async () => {
        updateScheduleMock.mockResolvedValue(job({ enabled: false }));
        listSchedulesMock.mockResolvedValue([job()]);
        render(<SchedulesManagerContent agents={agents} />);

        await screen.findByText("早报");
        fireEvent.click(screen.getByRole("switch"));

        await waitFor(() =>
            expect(updateScheduleMock).toHaveBeenCalledWith("job-1", {
                enabled: false,
            }),
        );
    });

    it("runs once through runScheduleNow", async () => {
        runScheduleNowMock.mockResolvedValue("task-1");
        listSchedulesMock.mockResolvedValue([job()]);
        render(<SchedulesManagerContent agents={agents} />);

        await screen.findByText("早报");
        fireEvent.click(screen.getByLabelText("立即执行一次"));

        await waitFor(() =>
            expect(runScheduleNowMock).toHaveBeenCalledWith("job-1"),
        );
        expect(
            await screen.findByText("已触发执行一次（任务 task-1）。"),
        ).toBeTruthy();
    });

    it("deletes through deleteSchedule after confirming", async () => {
        deleteScheduleMock.mockResolvedValue(undefined);
        listSchedulesMock.mockResolvedValue([job()]);
        render(<SchedulesManagerContent agents={agents} />);

        await screen.findByText("早报");
        fireEvent.click(screen.getByLabelText("删除"));

        await screen.findByText("删除此任务？");
        expect(
            screen.getByText("「早报」将停止运行，且无法恢复。"),
        ).toBeTruthy();
        fireEvent.click(screen.getByText("删除"));

        await waitFor(() =>
            expect(deleteScheduleMock).toHaveBeenCalledWith("job-1"),
        );
    });
});
