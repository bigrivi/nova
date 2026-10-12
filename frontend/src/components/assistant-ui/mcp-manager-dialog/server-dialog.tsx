import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2Icon, PlusIcon, Trash2Icon } from "lucide-react";

import {
    addMcpServer,
    deleteMcpServer,
    testMcpServer,
    updateMcpServer,
} from "../../../lib/nova-api";
import { cn } from "../../../lib/utils";
import { Button } from "../../ui/button";
import { ConfirmDialog } from "../../ui/confirm-dialog";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "../../ui/dialog";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "../../ui/select";
import {
    TRANSPORT_VALUES,
    formStateFromRecord,
    inputClassName,
    isTestable,
    toInput,
    type McpFormState,
    type McpKeyValue,
    type NovaMcpServerRecord,
} from "./types";

type McpServerDialogProps = {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** undefined = create mode, otherwise edit mode for this server. */
    server?: NovaMcpServerRecord;
    onMutated: (next: NovaMcpServerRecord[]) => void;
    onStatusChange: (message: string | null) => void;
};

type TestState =
    | { kind: "idle" }
    | { kind: "running" }
    | { kind: "done"; ok: boolean; summary: string };

/** A repeating name/value row, used for both env vars and headers. */
function KeyValueRows({
    rows,
    onChange,
    nameLabel,
    valueLabel,
    disabled,
    hint,
}: {
    rows: McpKeyValue[];
    onChange: (rows: McpKeyValue[]) => void;
    nameLabel: string;
    valueLabel: string;
    disabled?: boolean;
    hint?: string;
}) {
    const { t } = useTranslation();
    function update(index: number, patch: Partial<McpKeyValue>) {
        onChange(
            rows.map((row, i) => (i === index ? { ...row, ...patch } : row)),
        );
    }
    return (
        <div className="space-y-1.5">
            <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-foreground">
                    {nameLabel}
                </span>
                <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-7 gap-1 px-2 text-xs"
                    disabled={disabled}
                    onClick={() => onChange([...rows, { key: "", value: "" }])}
                >
                    <PlusIcon className="size-3.5" />
                    {t("mcp.addRow")}
                </Button>
            </div>
            {hint ? (
                <p className="text-[11px] leading-snug text-muted-foreground">
                    {hint}
                </p>
            ) : null}
            {rows.map((row, index) => (
                <div key={index} className="flex items-center gap-1.5">
                    <input
                        value={row.key}
                        disabled={disabled}
                        onChange={(event) =>
                            update(index, { key: event.target.value })
                        }
                        className={cn(inputClassName, "flex-1")}
                        placeholder={t("mcp.keyPlaceholder")}
                        aria-label={nameLabel}
                    />
                    <input
                        type="password"
                        value={row.value}
                        disabled={disabled}
                        onChange={(event) =>
                            update(index, { value: event.target.value })
                        }
                        className={cn(inputClassName, "flex-1")}
                        placeholder={valueLabel}
                        aria-label={valueLabel}
                    />
                    <Button
                        type="button"
                        size="icon-sm"
                        variant="ghost"
                        disabled={disabled}
                        onClick={() =>
                            onChange(rows.filter((_, i) => i !== index))
                        }
                        aria-label={t("mcp.removeRow")}
                    >
                        <Trash2Icon className="size-3.5" />
                    </Button>
                </div>
            ))}
        </div>
    );
}

export function McpServerDialog({
    open,
    onOpenChange,
    server,
    onMutated,
    onStatusChange,
}: McpServerDialogProps) {
    const { t } = useTranslation();
    const isEdit = server !== undefined;
    const [form, setForm] = useState<McpFormState>(() =>
        formStateFromRecord(server),
    );
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState<TestState>({ kind: "idle" });
    const [confirmingDelete, setConfirmingDelete] = useState(false);

    const busy = saving || testing.kind === "running";

    function patch(changes: Partial<McpFormState>) {
        setForm((current) => ({ ...current, ...changes }));
        // A stale verdict is worse than none: the user edits the command and the
        // panel still says "connected" for the command before it.
        setTesting({ kind: "idle" });
    }

    function fail(message: unknown) {
        const text = message instanceof Error ? message.message : String(message);
        setError(text);
        onStatusChange(text);
    }

    /**
     * Connect the config as the form currently stands, without saving it.
     *
     * This is the point of the button: a saved config is inert until Nova
     * restarts, so the user needs proof of reachability *before* committing.
     */
    async function handleTest() {
        setError(null);
        onStatusChange(null);
        setTesting({ kind: "running" });
        try {
            const result = await testMcpServer(toInput(form));
            if (result.ok) {
                const who = result.server_name || form.name.trim();
                const summary =
                    result.tool_count === 0
                        ? t("mcp.testOkNoTools", { server: who })
                        : t("mcp.testOk", {
                              server: who,
                              count: result.tool_count,
                          });
                setTesting({ kind: "done", ok: true, summary });
            } else {
                setTesting({
                    kind: "done",
                    ok: false,
                    summary: result.error || t("mcp.testFailed"),
                });
            }
        } catch (caught) {
            const text =
                caught instanceof Error ? caught.message : String(caught);
            setTesting({ kind: "done", ok: false, summary: text });
        }
    }

    async function handleSave() {
        setError(null);
        onStatusChange(null);
        setSaving(true);
        try {
            const input = toInput(form);
            const next = isEdit
                ? await updateMcpServer(server.name, input)
                : await addMcpServer(input);
            onMutated(next);
            onOpenChange(false);
        } catch (caught) {
            fail(caught);
        } finally {
            setSaving(false);
        }
    }

    async function handleDelete() {
        if (!server) {
            return;
        }
        setSaving(true);
        try {
            onMutated(await deleteMcpServer(server.name));
            setConfirmingDelete(false);
            onOpenChange(false);
        } catch (caught) {
            fail(caught);
        } finally {
            setSaving(false);
        }
    }

    const isStdio = form.transport === "stdio";

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-h-[85dvh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle>
                        {isEdit
                            ? t("mcp.editDialogTitle")
                            : t("mcp.addDialogTitle")}
                    </DialogTitle>
                    <DialogDescription>
                        {isEdit
                            ? t("mcp.editDialogDescription")
                            : t("mcp.addDialogDescription")}
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-3">
                    <label className="block space-y-1">
                        <span className="text-xs font-medium text-foreground">
                            {t("mcp.name")}
                        </span>
                        <input
                            value={form.name}
                            disabled={busy}
                            onChange={(event) =>
                                patch({ name: event.target.value })
                            }
                            className={inputClassName}
                            placeholder={t("mcp.namePlaceholder")}
                        />
                    </label>

                    <div className="space-y-1">
                        <span className="text-xs font-medium text-foreground">
                            {t("mcp.transport")}
                        </span>
                        <Select
                            value={form.transport}
                            onValueChange={(value) =>
                                patch({
                                    transport: value as McpFormState["transport"],
                                })
                            }
                            disabled={busy}
                        >
                            <SelectTrigger
                                className="h-9 w-full rounded-lg"
                                aria-label={t("mcp.transport")}
                            >
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {TRANSPORT_VALUES.map((value) => (
                                    <SelectItem key={value} value={value}>
                                        {t(`mcp.transport_${value}`)}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    {isStdio ? (
                        <>
                            <label className="block space-y-1">
                                <span className="text-xs font-medium text-foreground">
                                    {t("mcp.command")}
                                </span>
                                <input
                                    value={form.command}
                                    disabled={busy}
                                    onChange={(event) =>
                                        patch({ command: event.target.value })
                                    }
                                    className={inputClassName}
                                    placeholder={t("mcp.commandPlaceholder")}
                                />
                            </label>
                            <div className="space-y-1.5">
                                <span className="text-xs font-medium text-foreground">
                                    {t("mcp.args")}
                                </span>
                                {form.args.map((arg, index) => (
                                    <div
                                        key={index}
                                        className="flex items-center gap-1.5"
                                    >
                                        <input
                                            value={arg}
                                            disabled={busy}
                                            onChange={(event) =>
                                                patch({
                                                    args: form.args.map(
                                                        (value, i) =>
                                                            i === index
                                                                ? event.target
                                                                      .value
                                                                : value,
                                                    ),
                                                })
                                            }
                                            className={cn(
                                                inputClassName,
                                                "flex-1 font-mono",
                                            )}
                                            placeholder={t("mcp.argsPlaceholder")}
                                            aria-label={t("mcp.args")}
                                        />
                                        <Button
                                            type="button"
                                            size="icon-sm"
                                            variant="ghost"
                                            disabled={busy}
                                            onClick={() =>
                                                patch({
                                                    args: form.args.filter(
                                                        (_, i) =>
                                                            i !== index,
                                                    ),
                                                })
                                            }
                                            aria-label={t("mcp.removeRow")}
                                        >
                                            <Trash2Icon className="size-3.5" />
                                        </Button>
                                    </div>
                                ))}
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="ghost"
                                    className="h-7 gap-1 px-2 text-xs"
                                    disabled={busy}
                                    onClick={() =>
                                        patch({ args: [...form.args, ""] })
                                    }
                                >
                                    <PlusIcon className="size-3.5" />
                                    {t("mcp.addRow")}
                                </Button>
                            </div>
                            <KeyValueRows
                                rows={form.env}
                                disabled={busy}
                                nameLabel={t("mcp.env")}
                                valueLabel={t("mcp.valuePlaceholder")}
                                hint={isEdit ? t("mcp.secretHint") : undefined}
                                onChange={(env) => patch({ env })}
                            />
                        </>
                    ) : (
                        <>
                            <label className="block space-y-1">
                                <span className="text-xs font-medium text-foreground">
                                    {t("mcp.url")}
                                </span>
                                <input
                                    value={form.url}
                                    disabled={busy}
                                    onChange={(event) =>
                                        patch({ url: event.target.value })
                                    }
                                    className={inputClassName}
                                    placeholder={t("mcp.urlPlaceholder")}
                                />
                            </label>
                            <KeyValueRows
                                rows={form.headers}
                                disabled={busy}
                                nameLabel={t("mcp.headers")}
                                valueLabel={t("mcp.valuePlaceholder")}
                                hint={isEdit ? t("mcp.secretHint") : undefined}
                                onChange={(headers) => patch({ headers })}
                            />
                        </>
                    )}

                    {/* The connection test: proves reachability now, because a
                        saved config stays inert until Nova restarts. */}
                    <div className="rounded-lg border bg-muted/30 p-3">
                        <div className="flex items-center gap-2">
                            <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                className="gap-1.5"
                                disabled={busy || !isTestable(form)}
                                onClick={() => void handleTest()}
                            >
                                {testing.kind === "running" ? (
                                    <Loader2Icon className="size-3.5 animate-spin" />
                                ) : null}
                                {testing.kind === "running"
                                    ? t("mcp.testing")
                                    : t("mcp.testConnection")}
                            </Button>
                            {!isTestable(form) ? (
                                <span className="text-[11px] text-muted-foreground">
                                    {isStdio
                                        ? t("mcp.testNeedsCommand")
                                        : t("mcp.testNeedsUrl")}
                                </span>
                            ) : null}
                        </div>
                        {testing.kind === "done" ? (
                            <p
                                className={cn(
                                    "mt-2 text-xs break-words",
                                    testing.ok
                                        ? "text-emerald-600 dark:text-emerald-400"
                                        : "text-destructive",
                                )}
                            >
                                {testing.summary}
                            </p>
                        ) : null}
                    </div>

                    {error ? (
                        <p className="text-xs text-destructive">{error}</p>
                    ) : null}
                </div>

                <DialogFooter>
                    {isEdit ? (
                        <Button
                            type="button"
                            size="sm"
                            variant="destructive"
                            disabled={busy}
                            onClick={() => setConfirmingDelete(true)}
                        >
                            {t("mcp.delete")}
                        </Button>
                    ) : null}
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                    >
                        {t("common.cancel")}
                    </Button>
                    <Button
                        type="button"
                        size="sm"
                        disabled={busy}
                        onClick={() => void handleSave()}
                    >
                        {isEdit ? t("common.save") : t("mcp.add")}
                    </Button>
                </DialogFooter>
            </DialogContent>
            {isEdit && confirmingDelete ? (
                <ConfirmDialog
                    open={confirmingDelete}
                    onOpenChange={setConfirmingDelete}
                    title={t("mcp.delete")}
                    description={t("mcp.confirmDelete")}
                    confirmLabel={t("mcp.delete")}
                    onConfirm={() => void handleDelete()}
                />
            ) : null}
        </Dialog>
    );
}