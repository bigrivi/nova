/** Scheduled jobs: what will run, when it ran last, and how to stop it */
import { useKeyboard } from "@opentui/react";
import { useState } from "react";
import {
    createSchedule,
    deleteSchedule,
    listSchedules,
    runScheduleNow,
    setScheduleEnabled,
} from "../../api/schedules.ts";
import type { NovaScheduleJob } from "../../api/types.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { useToastStore } from "../../stores/toast-store.ts";
import { useTheme } from "../../context/theme.tsx";
import {
    describeSchedule,
    jobSummary,
    parseScheduleInput,
    scheduleLine,
} from "../../lib/schedule-format.ts";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { ScreenPanel } from "./ScreenPanel.tsx";
import { SearchableList } from "./SearchableList.tsx";
import { useListScreen } from "./use-list-screen.ts";

/** The list row that opens the create wizard instead of selecting a job. */
const NEW_ROW = "__new__";

type Wizard = {
    step: "name" | "when" | "prompt";
    name: string;
    when: string;
    prompt: string;
};

export function SchedulesScreen() {
    const sessionId = useChatStore((state) => state.sessionId);
    const agentKey = useChatStore((state) => state.agentKey);
    const [selected, setSelected] = useState<NovaScheduleJob | null>(null);
    const [confirming, setConfirming] = useState(false);
    const [wizard, setWizard] = useState<Wizard | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const { items, ready, error: loadError, reload } = useListScreen(listSchedules);

    useKeyboard((key) => {
        if (!selected || wizard) return;
        if (key.name === "escape" || key.name === "q") {
            if (confirming) {
                setConfirming(false);
            } else {
                setSelected(null);
            }
            return;
        }
        if (key.name === "t") {
            void toggle(selected);
            return;
        }
        if (key.name === "r") {
            void runNow(selected);
            return;
        }
        if (key.name === "d") {
            setConfirming(true);
            return;
        }
        if (key.name === "y" && confirming) {
            void remove(selected);
        }
    });

    async function toggle(job: NovaScheduleJob): Promise<void> {
        try {
            const next = await setScheduleEnabled(job.id, !job.enabled);
            setSelected(next);
            reload();
        } catch (err) {
            report(err, "Toggle failed");
        }
    }

    async function runNow(job: NovaScheduleJob): Promise<void> {
        setBusy(true);
        try {
            await runScheduleNow(job.id);
            useToastStore
                .getState()
                .show(`Started “${job.name}” now; see /tasks for the run`, 4000);
            reload();
        } catch (err) {
            report(err, "Run failed");
        } finally {
            setBusy(false);
        }
    }

    async function remove(job: NovaScheduleJob): Promise<void> {
        setConfirming(false);
        try {
            await deleteSchedule(job.id);
            setSelected(null);
            reload();
            useToastStore.getState().show(`Deleted “${job.name}”`, 3000);
        } catch (err) {
            report(err, "Delete failed");
        }
    }

    function report(err: unknown, prefix: string): void {
        setError(err instanceof Error ? err.message : String(err));
        useToastStore.getState().show(`${prefix}: ${String(err)}`, 4000);
    }

    async function finish(current: Wizard): Promise<void> {
        const when = parseScheduleInput(current.when);
        if (!when) {
            setError("Schedule must be a cron expression (0 9 * * *) or minutes (30m)");
            return;
        }
        if (!sessionId) {
            setError("Open a session first: a job runs into a session");
            return;
        }
        try {
            await createSchedule({
                name: current.name.trim(),
                prompt: current.prompt.trim(),
                sessionId,
                agentKey,
                kind: when.kind,
                cronExpr: when.kind === "cron" ? when.cronExpr : undefined,
                intervalMinutes:
                    when.kind === "interval" ? when.intervalMinutes : undefined,
            });
            setWizard(null);
            setError("");
            reload();
            useToastStore.getState().show(`Scheduled “${current.name}”`, 3000);
        } catch (err) {
            report(err, "Create failed");
        }
    }

    if (!ready) {
        return <ScreenLoading message={loadError || "Loading schedules..."} />;
    }

    if (wizard) {
        return (
            <WizardPanel
                wizard={wizard}
                error={error}
                onChange={setWizard}
                onSubmit={(current) => {
                    if (current.step === "name") {
                        if (!current.name.trim()) {
                            setError("A job needs a name");
                            return;
                        }
                        setError("");
                        setWizard({ ...current, step: "when" });
                        return;
                    }
                    if (current.step === "when") {
                        if (!parseScheduleInput(current.when)) {
                            setError(
                                "Expected a cron expression (0 9 * * *) or minutes (30m)",
                            );
                            return;
                        }
                        setError("");
                        setWizard({ ...current, step: "prompt" });
                        return;
                    }
                    if (!current.prompt.trim()) {
                        setError("A job needs a prompt to run");
                        return;
                    }
                    void finish(current);
                }}
                onCancel={() => {
                    setWizard(null);
                    setError("");
                }}
            />
        );
    }

    if (selected) {
        return (
            <JobDetail job={selected} confirming={confirming} busy={busy} />
        );
    }

    return (
        <SearchableList
            title="Scheduled jobs"
            items={[
                { label: "＋ New scheduled job", value: NEW_ROW },
                ...items.map((job) => ({
                    label: scheduleLine(job),
                    value: job.id,
                })),
            ]}
            onSelect={(value) => {
                if (value === NEW_ROW) {
                    setWizard({ step: "name", name: "", when: "", prompt: "" });
                    return;
                }
                const job = items.find((entry) => entry.id === value);
                if (job) setSelected(job);
            }}
            onClose={() => useScreenStore.getState().close()}
            emptyText={loadError || "no scheduled jobs"}
        />
    );
}

function JobDetail({
    job,
    confirming,
    busy,
}: {
    job: NovaScheduleJob;
    confirming: boolean;
    busy: boolean;
}) {
    const theme = useTheme();
    const prompt = job.prompt.trim().split("\n").slice(0, 3).join("\n");
    return (
        <ScreenPanel width="75%">
            <box flexDirection="column" gap={1}>
                <text fg={theme.text.base} content={job.name} />
                <text fg={theme.text.muted} content={describeSchedule(job)} />
                <text fg={theme.text.muted} content={jobSummary(job)} />
                <text
                    fg={theme.text.faint}
                    content={`agent ${job.agent_key} · session ${job.session_id}`}
                />
                {job.last_error ? (
                    <text fg={theme.feedback.error} content={job.last_error} />
                ) : null}
                <text fg={theme.text.base} content={prompt} />
                <text
                    fg={confirming ? theme.feedback.error : theme.text.faint}
                    content={
                        confirming
                            ? `delete ${job.name}? y confirm · esc cancel`
                            : busy
                              ? "starting…"
                              : "t pause/resume · r run now · d delete · esc back"
                    }
                />
            </box>
        </ScreenPanel>
    );
}

function WizardPanel({
    wizard,
    error,
    onChange,
    onSubmit,
    onCancel,
}: {
    wizard: Wizard;
    error: string;
    onChange: (next: Wizard) => void;
    onSubmit: (current: Wizard) => void;
    onCancel: () => void;
}) {
    const theme = useTheme();
    const step = wizard.step;
    const value =
        step === "name" ? wizard.name : step === "when" ? wizard.when : wizard.prompt;
    const hint =
        step === "name"
            ? "name it something you will recognise in a list"
            : step === "when"
              ? "cron (0 9 * * *) or minutes (30m)"
              : "what the agent should do when it fires";

    return (
        <ScreenPanel width="70%">
            <box flexDirection="column" gap={1}>
                <text fg={theme.text.base} content="New scheduled job" />
                <text fg={theme.text.faint} content={`${step} · ${hint}`} />
                <input
                    key={step}
                    focused
                    value={value}
                    placeholder={hint}
                    placeholderColor={theme.text.faint}
                    textColor={theme.text.base}
                    focusedTextColor={theme.text.base}
                    onInput={(text) => onChange({ ...wizard, [step]: text })}
                    onSubmit={() => onSubmit(wizard)}
                />
                {error ? (
                    <text fg={theme.feedback.error} content={error} />
                ) : null}
                <text
                    fg={theme.text.faint}
                    content={
                        step === "prompt"
                            ? "⏎ create · esc cancel"
                            : "⏎ next · esc cancel"
                    }
                />
                <text
                    fg={theme.text.muted}
                    onMouseUp={onCancel}
                    content="cancel"
                />
            </box>
        </ScreenPanel>
    );
}
