import {
    CalendarClockIcon,
    CheckIcon,
    ChevronDownIcon,
    PencilIcon,
    PlayIcon,
    PlusIcon,
    RefreshCwIcon,
    Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { DRAFT_THREAD_ID } from "../../lib/nova-constants";
import {
    createSchedule,
    deleteSchedule,
    listSchedules,
    runScheduleNow,
    updateSchedule,
} from "../../lib/nova-api";
import {
    buildCreatePayload,
    CRON_PRESETS,
    defaultScheduleForm,
    describeSchedule,
    formatDateTime,
    scheduleFormFromJob,
    validateScheduleForm,
    type ScheduleFormField,
    type ScheduleFormValues,
} from "../../lib/schedule";
import { useConversationStore } from "../../stores/conversation-store";
import { useScheduleStore } from "../../stores/schedule-store";
import type { NovaAgent, NovaScheduleJob, NovaScheduleKind } from "../../types/nova";
import { Button } from "../ui/button";
import { ConfirmDialog } from "../ui/confirm-dialog";
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "../ui/dialog";
import { Input } from "../ui/input";
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
} from "../ui/command";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "../ui/popover";
import { Textarea } from "../ui/textarea";
import { cn } from "../../lib/utils";

const KIND_ORDER: NovaScheduleKind[] = ["cron", "interval", "once"];

const KIND_LABEL_KEY: Record<NovaScheduleKind, string> = {
    cron: "schedules.kindCron",
    interval: "schedules.kindInterval",
    once: "schedules.kindOnce",
};

const STATUS_LABEL_KEY: Record<string, string> = {
    running: "schedules.lastStatusRunning",
    succeeded: "schedules.lastStatusSucceeded",
    failed: "schedules.lastStatusFailed",
    skipped: "schedules.lastStatusSkipped",
    missed: "schedules.lastStatusMissed",
};

const STATUS_BADGE_CLASS: Record<string, string> = {
    running: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
    succeeded: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    failed: "bg-destructive/10 text-destructive",
    skipped: "bg-muted text-muted-foreground",
    missed: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
};

function shortId(id: string): string {
    return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

export function SchedulesManagerContent({ agents }: { agents: NovaAgent[] }) {
    const { t } = useTranslation();
    const schedules = useScheduleStore((state) => state.schedules);
    const loading = useScheduleStore((state) => state.loading);
    const loadError = useScheduleStore((state) => state.error);
    const currentThreadId = useConversationStore(
        (state) => state.currentThreadId,
    );
    const defaultSessionId =
        currentThreadId !== DRAFT_THREAD_ID ? currentThreadId : "";

    const [formOpen, setFormOpen] = useState(false);
    const [editing, setEditing] = useState<NovaScheduleJob | null>(null);
    const [deleting, setDeleting] = useState<NovaScheduleJob | null>(null);
    const [actingId, setActingId] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const refresh = useCallback(async () => {
        const store = useScheduleStore.getState();
        store.setLoading(true);
        try {
            store.setSchedules(await listSchedules());
        } catch (error) {
            store.setError(
                error instanceof Error ? error.message : String(error),
            );
        } finally {
            store.setLoading(false);
        }
    }, []);

    useEffect(() => {
        void refresh();
    }, [refresh]);

    function openCreate() {
        setEditing(null);
        setFormOpen(true);
    }

    function openEdit(job: NovaScheduleJob) {
        setEditing(job);
        setFormOpen(true);
    }

    async function handleToggle(job: NovaScheduleJob, enabled: boolean) {
        setActingId(job.id);
        setNotice(null);
        try {
            const next = await updateSchedule(job.id, { enabled });
            useScheduleStore.getState().upsertSchedule(next);
        } catch (error) {
            setNotice(error instanceof Error ? error.message : String(error));
        } finally {
            setActingId(null);
        }
    }

    async function handleRunNow(job: NovaScheduleJob) {
        setActingId(job.id);
        setNotice(null);
        try {
            const taskId = await runScheduleNow(job.id);
            setNotice(t("schedules.runStarted", { task: shortId(taskId) }));
            await refresh();
        } catch (error) {
            setNotice(error instanceof Error ? error.message : String(error));
        } finally {
            setActingId(null);
        }
    }

    async function handleDelete() {
        if (!deleting) {
            return;
        }
        setActingId(deleting.id);
        try {
            await deleteSchedule(deleting.id);
            useScheduleStore.getState().removeSchedule(deleting.id);
            setDeleting(null);
        } catch (error) {
            setNotice(error instanceof Error ? error.message : String(error));
        } finally {
            setActingId(null);
        }
    }

    return (
        <div className="pr-1">
            <div className="mb-3 flex items-center justify-between gap-2">
                <p className="text-[13px] text-muted-foreground">
                    {t("schedules.listHint")}
                </p>
                <div className="flex shrink-0 items-center gap-1.5">
                    <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t("common.refresh")}
                        title={t("common.refresh")}
                        disabled={loading}
                        onClick={() => void refresh()}
                    >
                        <RefreshCwIcon
                            className={cn("size-4", loading && "animate-spin")}
                        />
                    </Button>
                    <Button
                        type="button"
                        size="sm"
                        onClick={openCreate}
                        className="gap-1.5"
                    >
                        <PlusIcon className="size-4" />
                        {t("schedules.new")}
                    </Button>
                </div>
            </div>

            {notice ? (
                <p className="mb-3 rounded-lg border bg-card p-2.5 text-[13px] text-muted-foreground">
                    {notice}
                </p>
            ) : null}

            {loading && schedules.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">
                    {t("common.loading")}
                </p>
            ) : null}
            {!loading && loadError && schedules.length === 0 ? (
                <div className="py-6 text-center">
                    <p className="text-sm text-destructive">{loadError}</p>
                    <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="mt-3"
                        onClick={() => void refresh()}
                    >
                        {t("common.refresh")}
                    </Button>
                </div>
            ) : null}
            {!loading && !loadError && schedules.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">
                    {t("schedules.empty")}
                </p>
            ) : null}

            <div className="flex flex-col gap-2">
                {schedules.map((job) => (
                    <ScheduleRow
                        key={job.id}
                        job={job}
                        busy={actingId === job.id}
                        onToggle={(enabled) => void handleToggle(job, enabled)}
                        onRunNow={() => void handleRunNow(job)}
                        onEdit={() => openEdit(job)}
                        onDelete={() => setDeleting(job)}
                    />
                ))}
            </div>

            <ScheduleFormDialog
                open={formOpen}
                onOpenChange={setFormOpen}
                editing={editing}
                agents={agents}
                defaultSessionId={defaultSessionId}
            />
            <ConfirmDialog
                open={deleting !== null}
                onOpenChange={(next) => {
                    if (!next) {
                        setDeleting(null);
                    }
                }}
                title={t("schedules.deleteConfirmTitle")}
                description={
                    deleting
                        ? t("schedules.deleteConfirmDescription", {
                              name: deleting.name,
                          })
                        : undefined
                }
                confirmLabel={t("schedules.delete")}
                onConfirm={() => void handleDelete()}
            />
        </div>
    );
}

function ScheduleRow({
    job,
    busy,
    onToggle,
    onRunNow,
    onEdit,
    onDelete,
}: {
    job: NovaScheduleJob;
    busy: boolean;
    onToggle: (enabled: boolean) => void;
    onRunNow: () => void;
    onEdit: () => void;
    onDelete: () => void;
}) {
    const { t } = useTranslation();
    const threads = useConversationStore((state) => state.threads);
    const thread = threads.find((item) => item.id === job.session_id);
    const sessionText = thread
        ? `${thread.title || t("app.untitledSession")} ${shortId(job.session_id)}`
        : shortId(job.session_id);
    return (
        <div
            className={cn(
                "rounded-lg border bg-card p-3",
                !job.enabled && "opacity-60",
            )}
        >
            <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                        <span className="truncate text-sm font-medium">
                            {job.name}
                        </span>
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                            {t(KIND_LABEL_KEY[job.kind])}
                        </span>
                        {job.last_status ? (
                            <span
                                className={cn(
                                    "rounded px-1.5 py-0.5 text-[11px] font-medium",
                                    STATUS_BADGE_CLASS[job.last_status] ??
                                        "bg-muted text-muted-foreground",
                                )}
                            >
                                {t(
                                    STATUS_LABEL_KEY[job.last_status] ??
                                        "schedules.lastStatusUnknown",
                                )}
                            </span>
                        ) : null}
                    </div>
                    <p className="mt-1 flex items-center gap-1.5 text-[13px] text-muted-foreground">
                        <CalendarClockIcon className="size-3.5 shrink-0" />
                        <span className="truncate">
                            {describeSchedule(job, t)}
                        </span>
                    </p>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground/70">
                        {t("schedules.nextRun", {
                            time: formatDateTime(job.next_run_at),
                        })}
                        {" · "}
                        {t("schedules.sessionLabel", {
                            session: sessionText,
                        })}
                        {thread ? null : (
                            <span className="ml-1 rounded bg-amber-500/10 px-1.5 py-0.5 text-[11px] font-medium text-amber-600 dark:text-amber-400">
                                {t("schedules.sessionMissing")}
                            </span>
                        )}
                    </p>
                    {job.last_run_at ? (
                        <p className="mt-0.5 truncate text-xs text-muted-foreground/70">
                            {t("schedules.lastRun", {
                                time: formatDateTime(job.last_run_at),
                            })}
                        </p>
                    ) : null}
                    {job.last_error ? (
                        <p className="mt-0.5 line-clamp-2 text-xs text-destructive/90">
                            {job.last_error}
                        </p>
                    ) : null}
                    <p className="mt-1 line-clamp-2 text-[13px] break-words text-muted-foreground">
                        {job.prompt}
                    </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                    <button
                        type="button"
                        role="switch"
                        aria-checked={job.enabled}
                        aria-label={t("schedules.enable")}
                        disabled={busy}
                        onClick={() => onToggle(!job.enabled)}
                        className={cn(
                            "relative h-[22px] w-[38px] shrink-0 rounded-full transition-colors after:absolute after:-inset-3 after:content-[''] disabled:opacity-50",
                            job.enabled ? "bg-brand" : "bg-muted",
                        )}
                    >
                        <span
                            aria-hidden
                            className={cn(
                                "absolute top-[3px] size-4 rounded-full bg-white shadow transition-all",
                                job.enabled ? "left-[18px]" : "left-[3px]",
                            )}
                        />
                    </button>
                    <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t("schedules.runNow")}
                        title={t("schedules.runNow")}
                        disabled={busy}
                        onClick={onRunNow}
                    >
                        <PlayIcon className="size-4" />
                    </Button>
                    <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t("schedules.edit")}
                        disabled={busy}
                        onClick={onEdit}
                    >
                        <PencilIcon className="size-4" />
                    </Button>
                    <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t("schedules.delete")}
                        disabled={busy}
                        onClick={onDelete}
                    >
                        <Trash2Icon className="size-4" />
                    </Button>
                </div>
            </div>
        </div>
    );
}

function ScheduleFormDialog({
    open,
    onOpenChange,
    editing,
    agents,
    defaultSessionId,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    editing: NovaScheduleJob | null;
    agents: NovaAgent[];
    defaultSessionId: string;
}) {
    const { t } = useTranslation();
    const threads = useConversationStore((state) => state.threads);
    const currentThreadId = useConversationStore(
        (state) => state.currentThreadId,
    );
    const [values, setValues] = useState<ScheduleFormValues>(() =>
        defaultScheduleForm(),
    );
    const [errors, setErrors] = useState<
        Partial<Record<ScheduleFormField, string>>
    >({});
    const [serverError, setServerError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [sessionOpen, setSessionOpen] = useState(false);

    // Reset the form whenever the dialog opens for create vs. edit.
    useEffect(() => {
        if (!open) {
            return;
        }
        setErrors({});
        setServerError(null);
        setSessionOpen(false);
        setValues(
            editing
                ? scheduleFormFromJob(editing)
                : defaultScheduleForm({ sessionId: defaultSessionId }),
        );
    }, [open, editing, defaultSessionId]);

    function set<K extends keyof ScheduleFormValues>(
        key: K,
        value: ScheduleFormValues[K],
    ) {
        setValues((prev) => ({ ...prev, [key]: value }));
        setErrors((prev) => {
            if (!(key in prev)) {
                return prev;
            }
            const next = { ...prev };
            delete next[key as ScheduleFormField];
            return next;
        });
    }

    async function handleSave() {
        const found = validateScheduleForm(values, (key, options) =>
            t(key, options),
        );
        setErrors(found);
        if (Object.keys(found).length > 0) {
            return;
        }
        setSaving(true);
        setServerError(null);
        try {
            if (editing) {
                const next = await updateSchedule(
                    editing.id,
                    buildCreatePayload(values),
                );
                useScheduleStore.getState().upsertSchedule(next);
            } else {
                const created = await createSchedule(buildCreatePayload(values));
                useScheduleStore.getState().upsertSchedule(created);
            }
            onOpenChange(false);
        } catch (error) {
            setServerError(
                error instanceof Error ? error.message : String(error),
            );
        } finally {
            setSaving(false);
        }
    }

    const inputClassName =
        "h-9 w-full rounded-lg border bg-background px-3 text-base outline-none focus:border-ring focus:ring-2 focus:ring-ring/20 sm:text-sm";
    const labelClassName = "mb-1 block text-[13px] font-medium";
    const errorClassName = "mt-1 text-xs text-destructive";

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-lg">
                <DialogHeader>
                    <DialogTitle>
                        {editing ? t("schedules.editTitle") : t("schedules.newTitle")}
                    </DialogTitle>
                    <DialogDescription>
                        {t("schedules.formDescription")}
                    </DialogDescription>
                </DialogHeader>

                <div className="flex flex-col gap-4">
                    <div>
                        <span className={labelClassName}>
                            {t("schedules.kind")}
                        </span>
                        <div className="flex w-full rounded-lg border border-border p-0.5">
                            {KIND_ORDER.map((kind) => {
                                const active = values.kind === kind;
                                return (
                                    <button
                                        key={kind}
                                        type="button"
                                        onClick={() => set("kind", kind)}
                                        className={cn(
                                            "flex min-h-[36px] flex-1 items-center justify-center rounded-[7px] px-2 py-1.5 text-[13px] transition-colors",
                                            active
                                                ? "bg-brand text-on-brand"
                                                : "text-weak-strong hover:bg-muted/60",
                                        )}
                                    >
                                        {t(KIND_LABEL_KEY[kind])}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    <div>
                        <label className={labelClassName} htmlFor="schedule-name">
                            {t("schedules.name")}
                        </label>
                        <Input
                            id="schedule-name"
                            value={values.name}
                            onChange={(event) => set("name", event.target.value)}
                            placeholder={t("schedules.namePlaceholder")}
                            aria-invalid={!!errors.name}
                        />
                        {errors.name ? (
                            <p className={errorClassName}>{errors.name}</p>
                        ) : null}
                    </div>

                    <div>
                        <label
                            className={labelClassName}
                            htmlFor="schedule-prompt"
                        >
                            {t("schedules.prompt")}
                        </label>
                        <Textarea
                            id="schedule-prompt"
                            value={values.prompt}
                            onChange={(event) =>
                                set("prompt", event.target.value)
                            }
                            placeholder={t("schedules.promptPlaceholder")}
                            rows={3}
                            aria-invalid={!!errors.prompt}
                        />
                        {errors.prompt ? (
                            <p className={errorClassName}>{errors.prompt}</p>
                        ) : null}
                    </div>

                    {values.kind === "cron" ? (
                        <div>
                            <label
                                className={labelClassName}
                                htmlFor="schedule-cron"
                            >
                                {t("schedules.cronExpr")}
                            </label>
                            <Input
                                id="schedule-cron"
                                value={values.cronExpr}
                                onChange={(event) =>
                                    set("cronExpr", event.target.value)
                                }
                                placeholder="0 9 * * *"
                                className="font-mono"
                                aria-invalid={!!errors.cronExpr}
                            />
                            <div className="mt-1.5 flex flex-wrap gap-1.5">
                                {CRON_PRESETS.map((preset) => (
                                    <button
                                        key={preset.expr}
                                        type="button"
                                        onClick={() =>
                                            set("cronExpr", preset.expr)
                                        }
                                        className={cn(
                                            "rounded-full border px-2.5 py-1 text-xs transition-colors",
                                            values.cronExpr.trim() ===
                                                preset.expr
                                                ? "border-brand bg-brand-soft text-brand"
                                                : "border-border text-muted-foreground hover:bg-muted/60",
                                        )}
                                    >
                                        {t(preset.labelKey)}
                                    </button>
                                ))}
                            </div>
                            {errors.cronExpr ? (
                                <p className={errorClassName}>
                                    {errors.cronExpr}
                                </p>
                            ) : null}
                        </div>
                    ) : null}

                    {values.kind === "interval" ? (
                        <div>
                            <label
                                className={labelClassName}
                                htmlFor="schedule-interval"
                            >
                                {t("schedules.intervalMinutes")}
                            </label>
                            <Input
                                id="schedule-interval"
                                type="number"
                                min={1}
                                step={1}
                                value={values.intervalMinutes}
                                onChange={(event) =>
                                    set("intervalMinutes", event.target.value)
                                }
                                aria-invalid={!!errors.intervalMinutes}
                            />
                            {errors.intervalMinutes ? (
                                <p className={errorClassName}>
                                    {errors.intervalMinutes}
                                </p>
                            ) : null}
                        </div>
                    ) : null}

                    {values.kind === "once" ? (
                        <div>
                            <label
                                className={labelClassName}
                                htmlFor="schedule-run-at"
                            >
                                {t("schedules.runAt")}
                            </label>
                            <Input
                                id="schedule-run-at"
                                type="datetime-local"
                                value={values.runAt}
                                onChange={(event) =>
                                    set("runAt", event.target.value)
                                }
                                aria-invalid={!!errors.runAt}
                            />
                            {errors.runAt ? (
                                <p className={errorClassName}>
                                    {errors.runAt}
                                </p>
                            ) : null}
                        </div>
                    ) : null}

                    <div>
                        <span
                            className={labelClassName}
                            id="schedule-session-label"
                        >
                            {t("schedules.session")}
                        </span>
                        <Popover
                            open={sessionOpen}
                            onOpenChange={setSessionOpen}
                        >
                            <PopoverTrigger asChild>
                                <button
                                    type="button"
                                    role="combobox"
                                    aria-haspopup="listbox"
                                    aria-expanded={sessionOpen}
                                    aria-label={t("schedules.session")}
                                    aria-labelledby="schedule-session-label"
                                    aria-invalid={!!errors.sessionId}
                                    onKeyDown={(event) => {
                                        // ARIA combobox: arrows open the listbox from a focused trigger.
                                        if (
                                            event.key === "ArrowDown" ||
                                            event.key === "ArrowUp"
                                        ) {
                                            event.preventDefault();
                                            setSessionOpen(true);
                                        }
                                    }}
                                    onClick={() =>
                                        setSessionOpen((prev) => !prev)
                                    }
                                    className="inline-flex h-9 w-full items-center justify-between gap-2 rounded-lg border bg-background px-3 py-2 text-sm shadow-xs outline-none transition-colors focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/20 [&_span]:truncate"
                                >
                                    {(() => {
                                        const selected = threads.find(
                                            (thread) =>
                                                thread.id ===
                                                values.sessionId,
                                        );
                                        if (selected) {
                                            const title =
                                                selected.title ||
                                                t("app.untitledSession");
                                            const current =
                                                selected.id ===
                                                currentThreadId;
                                            return (
                                                <span className="flex min-w-0 flex-1 items-center overflow-hidden whitespace-nowrap">
                                                    <span className="min-w-0 flex-1 truncate text-left">
                                                        {title}
                                                    </span>{" "}
                                                    <span className="shrink-0 text-muted-foreground">
                                                        {shortId(selected.id)}
                                                    </span>
                                                    {current ? (
                                                        <>
                                                            {" "}
                                                            <span className="shrink-0 text-muted-foreground">
                                                                ·{" "}
                                                                {t(
                                                                    "schedules.sessionCurrent",
                                                                )}
                                                            </span>
                                                        </>
                                                    ) : null}
                                                </span>
                                            );
                                        }
                                        if (values.sessionId) {
                                            return (
                                                <span className="flex min-w-0 flex-1 items-center overflow-hidden whitespace-nowrap">
                                                    <span className="shrink-0">
                                                        {shortId(
                                                            values.sessionId,
                                                        )}
                                                    </span>{" "}
                                                    <span className="min-w-0 flex-1 truncate text-left">
                                                        ·{" "}
                                                        {t(
                                                            "schedules.sessionMissing",
                                                        )}
                                                    </span>
                                                </span>
                                            );
                                        }
                                        return (
                                            <span className="min-w-0 flex-1 truncate text-left text-muted-foreground/80">
                                                {t(
                                                    "schedules.sessionPlaceholder",
                                                )}
                                            </span>
                                        );
                                    })()}
                                    <ChevronDownIcon className="size-4 shrink-0 text-muted-foreground" />
                                </button>
                            </PopoverTrigger>
                            <PopoverContent
                                align="start"
                                className="w-(--radix-popover-trigger-width) max-w-(--radix-popover-trigger-width) p-0"
                            >
                                <Command>
                                    <CommandInput
                                        placeholder={t(
                                            "schedules.sessionSearch",
                                        )}
                                    />
                                    <CommandList>
                                        <CommandEmpty>
                                            {t("schedules.sessionEmpty")}
                                        </CommandEmpty>
                                        <CommandGroup>
                                            {threads.map((thread) => {
                                                const title =
                                                    thread.title ||
                                                    t(
                                                        "app.untitledSession",
                                                    );
                                                const current =
                                                    thread.id ===
                                                    currentThreadId;
                                                const selected =
                                                    thread.id ===
                                                    values.sessionId;
                                                return (
                                                    <CommandItem
                                                        key={thread.id}
                                                        value={`${title} ${thread.id} ${shortId(thread.id)}`}
                                                        keywords={[
                                                            thread.id,
                                                            shortId(
                                                                thread.id,
                                                            ),
                                                        ]}
                                                        onSelect={() => {
                                                            set(
                                                                "sessionId",
                                                                thread.id,
                                                            );
                                                            setSessionOpen(
                                                                false,
                                                            );
                                                        }}
                                                    >
                                                        <span className="flex min-w-0 flex-1 items-center overflow-hidden whitespace-nowrap">
                                                            <span className="min-w-0 flex-1 truncate">
                                                                {title}
                                                            </span>{" "}
                                                            <span className="shrink-0 text-muted-foreground">
                                                                {shortId(
                                                                    thread.id,
                                                                )}
                                                            </span>
                                                            {current ? (
                                                                <>
                                                                    {" "}
                                                                    <span className="shrink-0 text-muted-foreground">
                                                                        ·{" "}
                                                                        {t(
                                                                            "schedules.sessionCurrent",
                                                                        )}
                                                                    </span>
                                                                </>
                                                            ) : null}
                                                        </span>
                                                        {selected ? (
                                                            <CheckIcon className="size-3.5 shrink-0 text-primary" />
                                                        ) : null}
                                                    </CommandItem>
                                                );
                                            })}
                                            {values.sessionId &&
                                            !threads.some(
                                                (thread) =>
                                                    thread.id ===
                                                    values.sessionId,
                                            ) ? (
                                                <CommandItem
                                                    value={`${values.sessionId} ${shortId(values.sessionId)} ${t("schedules.sessionMissing")}`}
                                                    keywords={[
                                                        values.sessionId,
                                                        shortId(
                                                            values.sessionId,
                                                        ),
                                                    ]}
                                                    onSelect={() => {
                                                        setSessionOpen(false);
                                                    }}
                                                >
                                                    <span className="flex min-w-0 flex-1 items-center overflow-hidden whitespace-nowrap">
                                                        <span className="shrink-0">
                                                            {shortId(
                                                                values.sessionId,
                                                            )}
                                                        </span>{" "}
                                                        <span className="min-w-0 flex-1 truncate">
                                                            ·{" "}
                                                            {t(
                                                                "schedules.sessionMissing",
                                                            )}
                                                        </span>
                                                    </span>
                                                    <CheckIcon className="size-3.5 shrink-0 text-primary" />
                                                </CommandItem>
                                            ) : null}
                                        </CommandGroup>
                                    </CommandList>
                                </Command>
                            </PopoverContent>
                        </Popover>
                        {errors.sessionId ? (
                            <p className={errorClassName}>
                                {errors.sessionId}
                            </p>
                        ) : null}
                    </div>

                    <div>
                        <label
                            className={labelClassName}
                            htmlFor="schedule-agent"
                        >
                            {t("schedules.agent")}
                        </label>
                        <select
                            id="schedule-agent"
                            value={values.agentKey}
                            onChange={(event) =>
                                set("agentKey", event.target.value)
                            }
                            className={inputClassName}
                        >
                            {agents.map((agent) => (
                                <option key={agent.key} value={agent.key}>
                                    {agent.name || agent.key}
                                </option>
                            ))}
                            {!agents.some(
                                (agent) => agent.key === values.agentKey,
                            ) ? (
                                <option value={values.agentKey}>
                                    {values.agentKey}
                                </option>
                            ) : null}
                        </select>
                    </div>

                    {serverError ? (
                        <p className="text-sm text-destructive">
                            {serverError}
                        </p>
                    ) : null}
                </div>

                <DialogFooter>
                    <DialogClose asChild>
                        <Button type="button" variant="outline">
                            {t("common.cancel")}
                        </Button>
                    </DialogClose>
                    <Button
                        type="button"
                        disabled={saving}
                        onClick={() => void handleSave()}
                    >
                        {saving
                            ? t("common.loading")
                            : editing
                              ? t("modelSelector.saveChanges")
                              : t("agentManager.create")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
