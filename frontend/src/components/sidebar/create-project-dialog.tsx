"use client";

import { FolderIcon, XIcon } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

import { ProjectPathPicker } from "./project-path-picker";

export function CreateProjectDialog({
    open,
    onOpenChange,
    onCreate,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onCreate: (name: string, path: string | null) => Promise<void> | void;
}) {
    const { t } = useTranslation();
    const [name, setName] = useState("");
    const [path, setPath] = useState("");
    const [pickerOpen, setPickerOpen] = useState(false);
    const trimmedName = name.trim();

    const reset = () => {
        setName("");
        setPath("");
    };

    const submit = () => {
        if (!trimmedName) {
            return;
        }
        void onCreate(trimmedName, path.trim() || null);
        reset();
        onOpenChange(false);
    };

    return (
        <Dialog
            open={open}
            onOpenChange={(next) => {
                onOpenChange(next);
                if (!next) {
                    reset();
                }
            }}
        >
            <DialogContent showCloseButton={false} className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>{t("sidebar.newProject")}</DialogTitle>
                    <DialogDescription>
                        {t("sidebar.createProjectDescription")}
                    </DialogDescription>
                </DialogHeader>
                <div className="mt-2 flex flex-col gap-2.5">
                    <input
                        autoFocus
                        value={name}
                        onChange={(event) => setName(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === "Enter") submit();
                        }}
                        placeholder={t("sidebar.projectNamePlaceholder")}
                        aria-label={t("sidebar.projectNamePlaceholder")}
                        className="w-full rounded-[9px] border border-border bg-card px-3 py-2 text-sm text-foreground outline-none focus:border-brand"
                    />
                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={() => setPickerOpen(true)}
                            aria-label={t("sidebar.projectPathPlaceholder")}
                            className="flex min-w-0 flex-1 items-center gap-2 rounded-[9px] border border-border bg-card px-3 py-2 text-left text-sm text-foreground hover:border-brand"
                        >
                            <FolderIcon className="size-4 shrink-0 text-weak" />
                            <span
                                className={cn(
                                    "min-w-0 flex-1 truncate",
                                    !path && "text-weak",
                                )}
                            >
                                {path || t("sidebar.projectPathPlaceholder")}
                            </span>
                        </button>
                        {path ? (
                            <button
                                type="button"
                                onClick={() => setPath("")}
                                aria-label={t("sidebar.projectPathClear")}
                                className="flex size-8 shrink-0 items-center justify-center rounded-md text-weak hover:bg-muted/60 hover:text-foreground"
                            >
                                <XIcon className="size-4" />
                            </button>
                        ) : null}
                    </div>
                    <ProjectPathPicker
                        open={pickerOpen}
                        onOpenChange={setPickerOpen}
                        initialPath={path || null}
                        onSelect={(next) => setPath(next ?? "")}
                    />
                </div>
                <DialogFooter className="-mx-0 -mb-0 mt-3 border-t-0 bg-transparent p-0">
                    <DialogClose asChild>
                        <Button type="button" variant="outline">
                            {t("common.cancel")}
                        </Button>
                    </DialogClose>
                    <Button
                        type="button"
                        disabled={!trimmedName}
                        onClick={submit}
                    >
                        {t("sidebar.createProject")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
