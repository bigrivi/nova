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
    MoonIcon,
    SettingsIcon,
    SunIcon,
    SunMoonIcon,
    UsersIcon,
    type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { useThemeMode, type ThemeMode } from "@/lib/theme";
import { setZoomLevel, useZoomLevel } from "@/lib/use-zoom";
import {
    useCodeWrap,
    useContextRingVisible,
    useSendShortcut,
    type SendShortcut,
} from "@/lib/ui-prefs";

const ACTIVE_NAV_CLASS = "bg-brand-soft text-brand";
const IDLE_NAV_CLASS = "text-foreground hover:bg-muted/60";

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

const THEME_MODES: ReadonlyArray<{
    mode: ThemeMode;
    labelKey: string;
    icon: LucideIcon;
}> = [
    { mode: "light", labelKey: "settings.general.themeLight", icon: SunIcon },
    {
        mode: "system",
        labelKey: "settings.general.themeSystem",
        icon: SunMoonIcon,
    },
    { mode: "dark", labelKey: "settings.general.themeDark", icon: MoonIcon },
];

const SEND_SHORTCUTS: ReadonlyArray<{
    value: SendShortcut;
    labelKey: string;
}> = [
    { value: "enter", labelKey: "settings.general.sendEnter" },
    { value: "mod-enter", labelKey: "settings.general.sendModEnter" },
];

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
    const { mode: themeMode, setMode: setThemeMode } = useThemeMode();
    const zoom = useZoomLevel();
    const { value: sendShortcut, setValue: setSendShortcut } =
        useSendShortcut();
    const { enabled: codeWrap, setEnabled: setCodeWrap } = useCodeWrap();
    const { visible: ringVisible, setVisible: setRingVisible } =
        useContextRingVisible();

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
            <DialogContent className="h-[min(78vh,720px)] max-h-[calc(100dvh-2rem)] gap-0 overflow-hidden p-0 sm:max-w-4xl">
                <div className="flex h-full min-h-0 w-full min-w-0 flex-col sm:flex-row">
                    <nav className="flex shrink-0 gap-1 overflow-x-auto border-b border-border bg-sidebar p-2 sm:w-52 sm:flex-col sm:overflow-x-visible sm:overflow-y-auto sm:border-r sm:border-b-0 sm:p-3">
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
                                        "flex min-h-[44px] flex-1 items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[14px] whitespace-nowrap transition-colors sm:mb-1 sm:w-full sm:flex-none sm:last:mb-0",
                                        isActive ? ACTIVE_NAV_CLASS : IDLE_NAV_CLASS,
                                    )}
                                >
                                    <Icon className="size-4 shrink-0" />
                                    {t(item.labelKey)}
                                </button>
                            );
                        })}
                    </nav>
                    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                        <header className="shrink-0 border-b border-border px-4 py-4 pr-14 sm:px-6">
                            <DialogTitle className="text-[17px] font-semibold">
                                {t(sectionTitleKey[section])}
                            </DialogTitle>
                            <p className="mt-1 text-[13px] text-muted-foreground">
                                {t(sectionDescriptionKey[section])}
                            </p>
                        </header>
                        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
                            {section === "general" ? (
                                <>
                                <section className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6 border-b border-border pb-5">
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
                                    <div className="flex w-full rounded-lg border border-border p-0.5 sm:w-auto sm:shrink-0">
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
                                                        "flex min-h-[44px] flex-1 items-center justify-center gap-1.5 rounded-[7px] px-3 py-1.5 text-[13px] transition-colors sm:min-h-0 sm:flex-none",
                                                        isActive
                                                            ? "bg-brand text-on-brand"
                                                            : "text-weak-strong hover:bg-muted/60",
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
                                <section className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6 border-b border-border py-5">
                                    <div className="min-w-0">
                                        <h3 className="text-[14px] font-semibold">
                                            {t("settings.general.theme")}
                                        </h3>
                                        <p className="mt-1 text-[13px] text-muted-foreground">
                                            {t(
                                                "settings.general.themeDescription",
                                            )}
                                        </p>
                                    </div>
                                    <div className="flex w-full rounded-lg border border-border p-0.5 sm:w-auto sm:shrink-0">
                                        {THEME_MODES.map((item) => {
                                            const Icon = item.icon;
                                            const isActive =
                                                themeMode === item.mode;
                                            return (
                                                <button
                                                    key={item.mode}
                                                    type="button"
                                                    onClick={() =>
                                                        setThemeMode(item.mode)
                                                    }
                                                    className={cn(
                                                        "flex min-h-[44px] flex-1 items-center justify-center gap-1.5 rounded-[7px] px-3 py-1.5 text-[13px] transition-colors sm:min-h-0 sm:flex-none",
                                                        isActive
                                                            ? "bg-brand text-on-brand"
                                                            : "text-weak-strong hover:bg-muted/60",
                                                    )}
                                                >
                                                    <Icon className="size-3.5" />
                                                    {t(item.labelKey)}
                                                </button>
                                            );
                                        })}
                                    </div>
                                </section>
                                <section className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6 border-b border-border py-5">
                                    <div className="min-w-0">
                                        <h3 className="text-[14px] font-semibold">
                                            {t("settings.general.zoom")}
                                        </h3>
                                        <p className="mt-1 text-[13px] text-muted-foreground">
                                            {t(
                                                "settings.general.zoomDescription",
                                            )}
                                        </p>
                                    </div>
                                    <div className="flex min-h-[44px] shrink-0 items-center gap-3 self-start sm:self-auto">
                                        <span className="w-12 text-right text-[13px] tabular-nums text-weak-strong">
                                            {Math.round(zoom * 100)}%
                                        </span>
                                        <input
                                            type="range"
                                            min={50}
                                            max={200}
                                            step={10}
                                            value={Math.round(zoom * 100)}
                                            onChange={(event) =>
                                                setZoomLevel(
                                                    Number(event.target.value) /
                                                        100,
                                                )
                                            }
                                            aria-label={t(
                                                "settings.general.zoom",
                                            )}
                                            className="h-11 w-36 max-w-[46vw] accent-brand sm:h-auto"
                                        />
                                    </div>
                                </section>
                                <section className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6 border-b border-border py-5">
                                    <div className="min-w-0">
                                        <h3 className="text-[14px] font-semibold">
                                            {t("settings.general.sendShortcut")}
                                        </h3>
                                        <p className="mt-1 text-[13px] text-muted-foreground">
                                            {t(
                                                "settings.general.sendShortcutDescription",
                                            )}
                                        </p>
                                    </div>
                                    <div className="flex w-full rounded-lg border border-border p-0.5 sm:w-auto sm:shrink-0">
                                        {SEND_SHORTCUTS.map((item) => {
                                            const isActive =
                                                sendShortcut === item.value;
                                            return (
                                                <button
                                                    key={item.value}
                                                    type="button"
                                                    onClick={() =>
                                                        setSendShortcut(
                                                            item.value,
                                                        )
                                                    }
                                                    className={cn(
                                                        "flex min-h-[44px] flex-1 items-center justify-center gap-1.5 rounded-[7px] px-3 py-1.5 text-[13px] transition-colors sm:min-h-0 sm:flex-none",
                                                        isActive
                                                            ? "bg-brand text-on-brand"
                                                            : "text-weak-strong hover:bg-muted/60",
                                                    )}
                                                >
                                                    {t(item.labelKey)}
                                                </button>
                                            );
                                        })}
                                    </div>
                                </section>
                                <section className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6 border-b border-border py-5">
                                    <div className="min-w-0">
                                        <h3 className="text-[14px] font-semibold">
                                            {t("settings.general.contextRing")}
                                        </h3>
                                        <p className="mt-1 text-[13px] text-muted-foreground">
                                            {t(
                                                "settings.general.contextRingDescription",
                                            )}
                                        </p>
                                    </div>
                                    <button
                                        type="button"
                                        role="switch"
                                        aria-checked={ringVisible}
                                        aria-label={t(
                                            "settings.general.contextRing",
                                        )}
                                        onClick={() =>
                                            setRingVisible(!ringVisible)
                                        }
                                        className={cn(
                                            "relative h-[22px] w-[38px] shrink-0 rounded-full transition-colors after:absolute after:-inset-3 after:content-['']",
                                            ringVisible
                                                ? "bg-brand"
                                                : "bg-muted",
                                        )}
                                    >
                                        <span
                                            aria-hidden
                                            className={cn(
                                                "absolute top-[3px] size-4 rounded-full bg-white shadow transition-all",
                                                ringVisible
                                                    ? "left-[18px]"
                                                    : "left-[3px]",
                                            )}
                                        />
                                    </button>
                                </section>
                                <section className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6 py-5">
                                    <div className="min-w-0">
                                        <h3 className="text-[14px] font-semibold">
                                            {t("settings.general.codeWrap")}
                                        </h3>
                                        <p className="mt-1 text-[13px] text-muted-foreground">
                                            {t(
                                                "settings.general.codeWrapDescription",
                                            )}
                                        </p>
                                    </div>
                                    <button
                                        type="button"
                                        role="switch"
                                        aria-checked={codeWrap}
                                        aria-label={t(
                                            "settings.general.codeWrap",
                                        )}
                                        onClick={() =>
                                            setCodeWrap(!codeWrap)
                                        }
                                        className={cn(
                                            "relative h-[22px] w-[38px] shrink-0 rounded-full transition-colors after:absolute after:-inset-3 after:content-['']",
                                            codeWrap
                                                ? "bg-brand"
                                                : "bg-muted",
                                        )}
                                    >
                                        <span
                                            aria-hidden
                                            className={cn(
                                                "absolute top-[3px] size-4 rounded-full bg-white shadow transition-all",
                                                codeWrap
                                                    ? "left-[18px]"
                                                    : "left-[3px]",
                                            )}
                                        />
                                    </button>
                                </section>
                                </>
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
