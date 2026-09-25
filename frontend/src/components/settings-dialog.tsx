import { useState } from "react";

import { AgentsManagerContent } from "@/components/assistant-ui/agents-manager-dialog";
import { MemoryManagerContent } from "@/components/assistant-ui/memory-manager-dialog";
import { ModelsManagerContent } from "@/components/assistant-ui/models-manager-dialog";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import type {
    NovaAgent,
    NovaModelRecord,
    NovaProviderRecord,
} from "@/types/nova";
import {
    CheckIcon,
    CpuIcon,
    DatabaseIcon,
    SettingsIcon,
    UsersIcon,
    type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

const ACTIVE_NAV_CLASS = "bg-[#EAF2FB] text-[#1D5FA8]";
const IDLE_NAV_CLASS = "text-[#201F1C] hover:bg-[#F0EEE7]";

type SettingsSection = "general" | "memory" | "models" | "agents";

const SECTIONS: ReadonlyArray<{
    id: SettingsSection;
    labelKey: string;
    icon: LucideIcon;
}> = [
    { id: "general", labelKey: "settings.section.general", icon: SettingsIcon },
    { id: "memory", labelKey: "settings.section.memory", icon: DatabaseIcon },
    { id: "models", labelKey: "settings.section.models", icon: CpuIcon },
    { id: "agents", labelKey: "settings.section.agents", icon: UsersIcon },
];

const LANGUAGES = [
    { code: "zh-CN", label: "简体中文" },
    { code: "en", label: "English" },
] as const;

export interface SettingsDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    agents: NovaAgent[];
    models: NovaModelRecord[];
    providers: NovaProviderRecord[];
    onAgentsChanged: (agents: NovaAgent[]) => void;
    onModelsUpdated: (models: NovaModelRecord[]) => void;
    onProvidersRefresh: () => Promise<void>;
    onConfigStatusChange: (message: string | null) => void;
}

/**
 * The single settings surface: a left nav selects a section, the right pane
 * hosts that section's content. The three manager sections reuse the same
 * content components the standalone dialogs rendered, so behaviour is
 * unchanged; only the surrounding chrome moved.
 */
export function SettingsDialog({
    open,
    onOpenChange,
    agents,
    models,
    providers,
    onAgentsChanged,
    onModelsUpdated,
    onProvidersRefresh,
    onConfigStatusChange,
}: SettingsDialogProps) {
    const { t, i18n } = useTranslation();
    const [section, setSection] = useState<SettingsSection>("general");

    // The general section keeps a distinct title (Settings > General) while the
    // other three reuse their nav label, matching the reference layout.
    const sectionTitleKey: Record<SettingsSection, string> = {
        general: "settings.general.title",
        memory: "settings.section.memory",
        models: "settings.section.models",
        agents: "settings.section.agents",
    };
    const sectionDescriptionKey: Record<SettingsSection, string> = {
        general: "settings.general.description",
        memory: "memory.manageDescription",
        models: "modelSelector.managerDescription",
        agents: "agentManager.manageDescription",
    };

    function handleOpenChange(next: boolean) {
        if (!next) {
            setSection("general");
        }
        onOpenChange(next);
    }

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <DialogContent className="h-[min(78vh,720px)] gap-0 overflow-hidden p-0 sm:max-w-4xl">
                <div className="flex h-full min-h-0 w-full min-w-0">
                    <nav className="w-52 shrink-0 overflow-y-auto border-r border-border bg-[#FBFAF7] p-3">
                        {SECTIONS.map((item) => {
                            const Icon = item.icon;
                            const isActive = item.id === section;
                            return (
                                <button
                                    key={item.id}
                                    type="button"
                                    aria-current={isActive}
                                    onClick={() => setSection(item.id)}
                                    className={cn(
                                        "mb-1 flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-[14px] transition-colors last:mb-0",
                                        isActive ? ACTIVE_NAV_CLASS : IDLE_NAV_CLASS,
                                    )}
                                >
                                    <Icon className="size-4 shrink-0" />
                                    {t(item.labelKey)}
                                </button>
                            );
                        })}
                    </nav>
                    <div className="flex min-w-0 flex-1 flex-col">
                        <header className="shrink-0 border-b border-border px-6 py-4 pr-14">
                            <DialogTitle className="text-[17px] font-semibold">
                                {t(sectionTitleKey[section])}
                            </DialogTitle>
                            <p className="mt-1 text-[13px] text-muted-foreground">
                                {t(sectionDescriptionKey[section])}
                            </p>
                        </header>
                        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto px-6 py-5">
                            {section === "general" ? (
                                <section className="flex items-start justify-between gap-6 border-b border-border pb-5">
                                    <div className="min-w-0">
                                        <h3 className="text-[14px] font-semibold">
                                            {t("settings.general.language")}
                                        </h3>
                                        <p className="mt-1 text-[13px] text-muted-foreground">
                                            {t(
                                                "settings.general.languageDescription",
                                            )}
                                        </p>
                                    </div>
                                    <div className="flex shrink-0 rounded-lg border border-border p-0.5">
                                        {LANGUAGES.map((language) => {
                                            const isActive =
                                                i18n.language === language.code;
                                            return (
                                                <button
                                                    key={language.code}
                                                    type="button"
                                                    onClick={() =>
                                                        void i18n.changeLanguage(
                                                            language.code,
                                                        )
                                                    }
                                                    className={cn(
                                                        "flex items-center gap-1.5 rounded-[7px] px-3 py-1.5 text-[13px] transition-colors",
                                                        isActive
                                                            ? "bg-[#1D5FA8] text-white"
                                                            : "text-[#6E6A60] hover:bg-[#F0EEE7]",
                                                    )}
                                                >
                                                    {isActive ? (
                                                        <CheckIcon className="size-3.5" />
                                                    ) : null}
                                                    {language.label}
                                                </button>
                                            );
                                        })}
                                    </div>
                                </section>
                            ) : null}
                            {section === "memory" ? <MemoryManagerContent /> : null}
                            {section === "models" ? (
                                <ModelsManagerContent
                                    providers={providers}
                                    models={models}
                                    onModelsUpdated={onModelsUpdated}
                                    onProvidersRefresh={onProvidersRefresh}
                                    onStatusChange={onConfigStatusChange}
                                />
                            ) : null}
                            {section === "agents" ? (
                                <AgentsManagerContent
                                    agents={agents}
                                    models={models}
                                    onAgentsChanged={onAgentsChanged}
                                />
                            ) : null}
                        </div>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
