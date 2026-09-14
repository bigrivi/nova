"use client";

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
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent showCloseButton={false} className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>{t("sidebar.deleteProjectTitle")}</DialogTitle>
                    <DialogDescription>
                        {t("sidebar.deleteProjectDescription")}
                    </DialogDescription>
                </DialogHeader>
                <DialogFooter className="-mx-0 -mb-0 mt-2 border-t-0 bg-transparent p-0">
                    <DialogClose asChild>
                        <Button type="button" variant="outline">
                            {t("common.cancel")}
                        </Button>
                    </DialogClose>
                    <Button
                        type="button"
                        variant="destructive"
                        onClick={() => {
                            onConfirm();
                            onOpenChange(false);
                        }}
                    >
                        {t("sidebar.deleteProject")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
