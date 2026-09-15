"use client";

import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";

export function DeleteProjectDialog({
    open,
    onOpenChange,
    onConfirm,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onConfirm: () => void;
}) {
    const { t } = useTranslation();

    return (
        <ConfirmDialog
            open={open}
            onOpenChange={onOpenChange}
            title={t("sidebar.deleteProjectTitle")}
            description={t("sidebar.deleteProjectDescription")}
            confirmLabel={t("sidebar.deleteProject")}
            onConfirm={onConfirm}
        />
    );
}
