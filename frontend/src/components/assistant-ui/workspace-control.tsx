import { WorkspacePicker } from "@/components/assistant-ui/workspace-picker";
import { FolderIcon } from "lucide-react";
import { type FC, useState } from "react";
import { useTranslation } from "react-i18next";

type WorkspaceControlProps = {
    value: string | null;
    onChange: (path: string | null) => void;
};

function basename(path: string): string {
    const parts = path.split(/[/\\]+/).filter(Boolean);
    return parts[parts.length - 1] || path;
}

export const WorkspaceControl: FC<WorkspaceControlProps> = ({
    value,
    onChange,
}) => {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);

    return (
        <>
            <button
                type="button"
                onClick={() => setOpen(true)}
                title={value || t("workspace.defaultHint")}
                aria-label={t("workspace.label")}
                className="flex h-8 max-w-40 items-center gap-1.5 rounded-full border border-border/60 px-2.5 text-[11px] font-medium leading-none text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
            >
                <FolderIcon className="size-3.5 shrink-0" />
                <span className="min-w-0 truncate">
                    {value ? basename(value) : t("workspace.label")}
                </span>
            </button>
            <WorkspacePicker
                open={open}
                onOpenChange={setOpen}
                initialPath={value}
                onSelect={onChange}
            />
        </>
    );
};
