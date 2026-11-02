import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
    createProvider,
    deleteProvider,
    listProviderPresets,
    updateProvider,
} from "../../../lib/nova-api";
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
import type {
    NovaModelRecord,
    NovaProviderPreset,
    NovaProviderRecord,
} from "./types";
import {
    PROVIDER_TYPE_LABEL_KEYS,
    PROVIDER_TYPE_PLACEHOLDER_KEYS,
    PROVIDER_TYPE_VALUES,
    inputClassName,
    toEditState,
    type ProviderEditState,
    type ProviderFormState,
} from "./types";

type ProviderDialogProps = {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** undefined = create mode, otherwise edit mode for this provider. */
    provider?: NovaProviderRecord;
    onMutated: (nextModels: NovaModelRecord[]) => Promise<void>;
    onStatusChange: (message: string | null) => void;
    /** Called with the new key after a successful create. */
    onCreated?: (key: string) => void;
    /** Called after a successful delete in edit mode. */
    onDeleted?: () => void;
    /** Provider keys that already exist, so the preset list can mark them. */
    connectedKeys?: string[];
};

export function ProviderDialog({
    open,
    onOpenChange,
    provider,
    onMutated,
    onStatusChange,
    onCreated,
    onDeleted,
    connectedKeys = [],
}: ProviderDialogProps) {
    const { t } = useTranslation();
    const isEdit = provider !== undefined;
    const [form, setForm] = useState<ProviderFormState>(() => ({
        key: "",
        type: "openai-compatible",
        name: "",
        baseUrl: "",
        apiKey: "",
    }));
    const [editState, setEditState] = useState<ProviderEditState>(() =>
        toEditState(provider),
    );
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [confirmingDelete, setConfirmingDelete] = useState(false);
    const [presets, setPresets] = useState<NovaProviderPreset[]>([]);
    const [presetId, setPresetId] = useState("");

    useEffect(() => {
        if (!open || isEdit) return;
        let cancelled = false;
        listProviderPresets()
            .then((items) => {
                if (!cancelled) setPresets(items);
            })
            .catch(() => {
                // No preset list only means the form stays manual.
                if (!cancelled) setPresets([]);
            });
        return () => {
            cancelled = true;
        };
    }, [open, isEdit]);

    function applyPreset(id: string) {
        setPresetId(id);
        const preset = presets.find((item) => item.id === id);
        if (!preset) return;
        setForm((current) => ({
            ...current,
            key: preset.id,
            name: preset.label,
            type: preset.type as ProviderFormState["type"],
            baseUrl: preset.base_url,
        }));
    }

    const activePreset = presets.find((item) => item.id === presetId);

    function fail(message: unknown) {
        const text = message instanceof Error ? message.message : String(message);
        setError(text);
        onStatusChange(text);
    }

    async function handleCreate() {
        setError(null);
        onStatusChange(null);
        setSaving(true);
        try {
            const { models, warning } = await createProvider({
                key: form.key,
                type: form.type,
                name: form.name,
                base_url: form.baseUrl,
                api_key: form.apiKey,
                // A key the preset list does not know is the user's own
                // endpoint: its model list is a declaration, not a catalogue.
                custom: !presets.some((item) => item.id === form.key),
            });
            await onMutated(models);
            // The provider is saved either way; a failed catalogue read is a
            // status line, not an error that keeps the dialog open.
            onStatusChange(warning);
            onCreated?.(form.key);
            onOpenChange(false);
        } catch (error) {
            fail(error);
        } finally {
            setSaving(false);
        }
    }

    async function handleUpdate() {
        if (!provider) return;
        setError(null);
        onStatusChange(null);
        setSaving(true);
        try {
            const payload: {
                name?: string;
                type?: string;
                base_url?: string;
                api_key?: string;
            } = {
                name: editState.name,
                type: editState.type,
                base_url: editState.baseUrl,
            };
            if (editState.apiKey) {
                payload.api_key = editState.apiKey;
            }
            const nextModels = await updateProvider(provider.key, payload);
            await onMutated(nextModels);
            onOpenChange(false);
        } catch (error) {
            fail(error);
        } finally {
            setSaving(false);
        }
    }

    async function handleDelete() {
        if (!provider) return;
        setError(null);
        onStatusChange(null);
        setSaving(true);
        try {
            const nextModels = await deleteProvider(provider.key);
            await onMutated(nextModels);
            onDeleted?.();
            onOpenChange(false);
        } catch (error) {
            fail(error);
        } finally {
            setSaving(false);
        }
    }

    const typeValue = isEdit ? editState.type : form.type;
    const setType = (value: string) => {
        if (isEdit) {
            setEditState((current) => ({
                ...current,
                type: value as ProviderEditState["type"],
            }));
        } else {
            setForm((current) => ({
                ...current,
                type: value as ProviderFormState["type"],
            }));
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-h-[85dvh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle>
                        {isEdit
                            ? t("modelSelector.editProvider")
                            : t("modelSelector.addProviderDialogTitle")}
                    </DialogTitle>
                    <DialogDescription>
                        {isEdit
                            ? t("modelSelector.editProviderDialogDescription")
                            : t("modelSelector.addProviderDialogDescription")}
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-3">
                    {!isEdit && presets.length > 0 ? (
                        <div className="space-y-1">
                            <span className="text-xs font-medium text-foreground">
                                {t("modelSelector.preset")}
                            </span>
                            <Select value={presetId} onValueChange={applyPreset}>
                                <SelectTrigger className="h-9 rounded-lg">
                                    <SelectValue
                                        placeholder={t(
                                            "modelSelector.presetPlaceholder",
                                        )}
                                    />
                                </SelectTrigger>
                                <SelectContent>
                                    {presets.map((preset) => (
                                        <SelectItem
                                            key={preset.id}
                                            value={preset.id}
                                        >
                                            {connectedKeys.includes(preset.id)
                                                ? `${preset.label} ✓`
                                                : preset.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            {activePreset ? (
                                <p className="text-xs text-muted-foreground">
                                    {activePreset.note}
                                    {activePreset.key_env
                                        ? ` ${t("modelSelector.presetKeyHint", {
                                              env: activePreset.key_env,
                                          })}`
                                        : null}
                                </p>
                            ) : null}
                        </div>
                    ) : null}

                    {!isEdit ? (
                        <label className="block space-y-1">
                            <span className="text-xs font-medium text-foreground">
                                {t("modelSelector.providerKey")}
                            </span>
                            <input
                                value={form.key}
                                onChange={(event) =>
                                    setForm((current) => ({
                                        ...current,
                                        key: event.target.value,
                                    }))
                                }
                                className={inputClassName}
                                placeholder={t(
                                    "modelSelector.providerKeyPlaceholder",
                                )}
                            />
                        </label>
                    ) : (
                        <p className="rounded-lg bg-muted/40 px-3 py-2 font-mono text-xs text-muted-foreground">
                            {provider.key}
                        </p>
                    )}

                    <label className="block space-y-1">
                        <span className="text-xs font-medium text-foreground">
                            {t("modelSelector.displayName")}
                        </span>
                        <input
                            value={isEdit ? editState.name : form.name}
                            onChange={(event) =>
                                isEdit
                                    ? setEditState((current) => ({
                                          ...current,
                                          name: event.target.value,
                                      }))
                                    : setForm((current) => ({
                                          ...current,
                                          name: event.target.value,
                                      }))
                            }
                            className={inputClassName}
                            placeholder={t(
                                "modelSelector.displayNamePlaceholder",
                            )}
                        />
                    </label>

                    <div className="space-y-1">
                        <span className="text-xs font-medium text-foreground">
                            {t("modelSelector.providerType")}
                        </span>
                        <Select value={typeValue} onValueChange={setType}>
                            <SelectTrigger className="h-9 rounded-lg">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {PROVIDER_TYPE_VALUES.map((value) => (
                                    <SelectItem key={value} value={value}>
                                        {t(PROVIDER_TYPE_LABEL_KEYS[value])}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    <label className="block space-y-1">
                        <span className="text-xs font-medium text-foreground">
                            {t("modelSelector.baseUrl")}
                        </span>
                        <input
                            value={isEdit ? editState.baseUrl : form.baseUrl}
                            onChange={(event) =>
                                isEdit
                                    ? setEditState((current) => ({
                                          ...current,
                                          baseUrl: event.target.value,
                                      }))
                                    : setForm((current) => ({
                                          ...current,
                                          baseUrl: event.target.value,
                                      }))
                            }
                            className={inputClassName}
                            placeholder={t(
                                PROVIDER_TYPE_PLACEHOLDER_KEYS[typeValue],
                            )}
                        />
                    </label>

                    {(isEdit ? editState.type : form.type) !== "ollama" ? (
                        <label className="block space-y-1">
                            <span className="text-xs font-medium text-foreground">
                                {t("modelSelector.apiKey")}
                            </span>
                            <input
                                type="password"
                                value={isEdit ? editState.apiKey : form.apiKey}
                                onChange={(event) =>
                                    isEdit
                                        ? setEditState((current) => ({
                                              ...current,
                                              apiKey: event.target.value,
                                          }))
                                        : setForm((current) => ({
                                              ...current,
                                              apiKey: event.target.value,
                                          }))
                                }
                                className={inputClassName}
                                placeholder={t(
                                    "modelSelector.apiKeyPlaceholder",
                                )}
                            />
                        </label>
                    ) : null}

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
                        disabled={saving}
                        onClick={() => setConfirmingDelete(true)}
                    >
                        {t("modelSelector.deleteProvider")}
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
                        disabled={saving}
                        onClick={() =>
                            void (isEdit ? handleUpdate() : handleCreate())
                        }
                    >
                        {isEdit
                            ? t("modelSelector.saveChanges")
                            : t("modelSelector.saveProvider")}
                    </Button>
                </DialogFooter>
            </DialogContent>
            {isEdit && confirmingDelete ? (
                <ConfirmDialog
                    open={confirmingDelete}
                    onOpenChange={setConfirmingDelete}
                    title={t("modelSelector.deleteProvider")}
                    description={t("modelSelector.confirmDeleteProvider")}
                    confirmLabel={t("modelSelector.delete")}
                    onConfirm={() => void handleDelete()}
                />
            ) : null}
        </Dialog>
    );
}
