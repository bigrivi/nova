"use client";

import {
    CheckIcon,
    ChevronRightIcon,
    DatabaseIcon,
    FolderIcon,
    LanguagesIcon,
    Loader2Icon,
    MessageCircleIcon,
    MoreHorizontalIcon,
    PanelLeftCloseIcon,
    PencilIcon,
    PinIcon,
    PlusIcon,
    SearchIcon,
    SettingsIcon,
    Trash2Icon,
} from "lucide-react";
import {
    Fragment,
    useEffect,
    useMemo,
    useRef,
    useState,
    type KeyboardEvent,
    type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import type { NovaProject, NovaThreadSummary } from "@/types/nova";

import {
    DATE_BUCKETS,
    dateBucket,
    groupThreads,
    nextThreadAfterDelete,
    orderedThreads,
    type SidebarProject,
} from "./sidebar-model";
import { HighlightedText } from "./highlight-text";
import { DeleteThreadDialog } from "./delete-thread-dialog";
import { DeleteProjectDialog } from "./delete-project-dialog";
import { CreateProjectDialog } from "./create-project-dialog";
import { MoveToProjectFlyout } from "./move-to-project-flyout";

type ThreadSidebarProps = {
    threads: NovaThreadSummary[];
    projects: NovaProject[];
    activeThreadId?: string;
    runningThreadId?: string;
    disabled: boolean;
    onCollapse: () => void;
    onNewThread: () => void;
    onNewThreadInProject: (projectId: string) => void;
    onCreateProject: (name: string, path?: string | null) => Promise<NovaProject | null>;
    onRenameProject: (projectId: string, name: string) => Promise<void> | void;
    onDeleteProject: (projectId: string) => Promise<void> | void;
    onSelectThread: (threadId: string) => void;
    onRenameThread: (threadId: string, title: string) => Promise<void> | void;
    onPinThread: (threadId: string, pinned: boolean) => Promise<void> | void;
    onMoveThread: (
        threadId: string,
        projectId: string | null,
    ) => Promise<void> | void;
    onDeleteThread: (
        threadId: string,
        nextThreadId: string | null,
    ) => Promise<void> | void;
    onOpenMemory: () => void;
};

const OPEN_PROJECTS_KEY = "nova.sidebar.open-projects.v2";
const COLLAPSED_SECTIONS_KEY = "nova.sidebar.collapsed-sections";
const SECTION_KEYS = ["pinned", "projects", "chats"] as const;
const OLDER_PAGE_SIZE = 50;

function readStoredStringSet(
    key: string,
    allowed?: readonly string[],
): Set<string> | null {
    const raw = localStorage.getItem(key);
    if (raw === null) {
        return null;
    }
    try {
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) {
            return null;
        }
        return new Set(
            parsed.filter(
                (item): item is string =>
                    typeof item === "string" &&
                    (!allowed || allowed.includes(item)),
            ),
        );
    } catch {
        return null;
    }
}

function writeStoredStringSet(key: string, values: Iterable<string>): void {
    localStorage.setItem(key, JSON.stringify([...values]));
}

function storedOpenProjects(): Set<string> | null {
    return readStoredStringSet(OPEN_PROJECTS_KEY);
}

function storedCollapsedSections(): Set<string> {
    return (
        readStoredStringSet(COLLAPSED_SECTIONS_KEY, SECTION_KEYS) ??
        new Set<string>()
    );
}

function defaultOpenProjects(projects: SidebarProject[]): Set<string> {
    return new Set(projects[0] ? [projects[0].id] : []);
}

function ThreadRow({
    thread,
    selected,
    running,
    projects,
    disabled,
    onSelect,
    onRename,
    onPin,
    onMove,
    onDelete,
    onCreateProject,
    showToast,
}: {
    thread: NovaThreadSummary;
    selected: boolean;
    running: boolean;
    projects: SidebarProject[];
    disabled: boolean;
    onSelect: () => void;
    onRename: (title: string) => Promise<void> | void;
    onPin: (pinned: boolean) => Promise<void> | void;
    onMove: (projectId: string | null) => Promise<void> | void;
    onDelete: () => Promise<void> | void;
    onCreateProject: (name: string, path?: string | null) => Promise<NovaProject | null>;
    showToast: (message: string) => void;
}) {
    const { t } = useTranslation();
    const [renaming, setRenaming] = useState(false);
    const [title, setTitle] = useState(thread.title);
    const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);
    const [flyoutAnchor, setFlyoutAnchor] = useState<{
        top: number;
        left: number;
        right: number;
    } | null>(null);
    const menuContentRef = useRef<HTMLDivElement | null>(null);
    const flyoutRef = useRef<HTMLDivElement | null>(null);

    const closeAll = () => {
        setFlyoutAnchor(null);
        setMenuOpen(false);
    };

    const saveRename = () => {
        const next = title.trim();
        setRenaming(false);
        if (!next || next === thread.title) {
            setTitle(thread.title);
            return;
        }
        void onRename(next);
    };

    const Icon = thread.pinned ? PinIcon : MessageCircleIcon;
    const currentProject = projects.find(
        (project) => project.id === thread.project_id,
    );

    return (
        <div
            className={cn(
                "group/thread flex min-h-8 items-center gap-1.5 rounded-lg px-2 py-1.5 text-[13.5px] transition-colors",
                selected
                    ? "bg-[#EAF1F9] font-semibold text-[#1D5FA8]"
                    : "text-[#201F1C] hover:bg-[#F0EEE7]",
            )}
        >
            <button
                type="button"
                disabled={disabled}
                onClick={onSelect}
                className="flex min-w-0 flex-1 items-center gap-2 text-left disabled:cursor-not-allowed"
                title={thread.title}
            >
                <Icon
                    className={cn(
                        "size-[15px] shrink-0",
                        thread.pinned ? "text-[#B7791F]" : selected ? "text-[#1D5FA8]" : "text-[#9C978A]",
                    )}
                />
                {renaming ? (
                    <input
                        autoFocus
                        value={title}
                        onClick={(event) => event.stopPropagation()}
                        onChange={(event) => setTitle(event.target.value)}
                        onBlur={saveRename}
                        onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
                            if (event.key === "Enter") saveRename();
                            if (event.key === "Escape") {
                                setTitle(thread.title);
                                setRenaming(false);
                            }
                        }}
                        className="min-w-0 flex-1 rounded-[5px] border border-[#1D5FA8] bg-white px-1.5 py-0.5 text-[13.5px] font-normal text-[#201F1C] outline-none"
                    />
                ) : (
                    <span className="truncate">{thread.title}</span>
                )}
                {running ? (
                    <Loader2Icon
                        aria-label={t("sidebar.running")}
                        className="size-3.5 shrink-0 animate-spin text-[#1D5FA8] motion-reduce:animate-none"
                    />
                ) : null}
            </button>

            {!renaming ? (
                <DropdownMenu
                    modal={false}
                    open={menuOpen}
                    onOpenChange={(open) => {
                        setMenuOpen(open);
                        if (!open) {
                            setFlyoutAnchor(null);
                        }
                    }}
                >
                    <DropdownMenuTrigger asChild>
                        <button
                            type="button"
                            className="thread-more flex size-[22px] shrink-0 items-center justify-center rounded-md text-[#9C978A] opacity-0 hover:bg-[#E5E2D9] hover:text-[#201F1C] focus-visible:opacity-100 data-[state=open]:opacity-100 group-hover/thread:opacity-100"
                            aria-label={t("threadList.moreActions")}
                        >
                            <MoreHorizontalIcon className="size-4" />
                        </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                        ref={menuContentRef}
                        align="start"
                        side="right"
                        collisionPadding={12}
                        className="w-52 border-[#E4E1D9] bg-white"
                        onFocusOutside={(event) => {
                            if (
                                flyoutRef.current?.contains(
                                    event.target as Node,
                                )
                            ) {
                                event.preventDefault();
                            }
                        }}
                        onInteractOutside={(event) => {
                            if (
                                flyoutRef.current?.contains(
                                    event.target as Node,
                                )
                            ) {
                                event.preventDefault();
                            }
                        }}
                        onEscapeKeyDown={(event) => {
                            if (flyoutAnchor) {
                                event.preventDefault();
                                closeAll();
                            }
                        }}
                    >
                        <DropdownMenuItem onSelect={() => setRenaming(true)}>
                            <PencilIcon className="size-4" />
                            {t("threadList.rename")}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            onSelect={() => {
                                void onPin(!thread.pinned);
                                showToast(t(thread.pinned ? "sidebar.unpinnedToast" : "sidebar.pinnedToast"));
                            }}
                        >
                            <PinIcon className="size-4 text-[#B7791F]" />
                            {t(thread.pinned ? "sidebar.unpin" : "sidebar.pin")}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            onSelect={(event) => {
                                event.preventDefault();
                                const rect =
                                    menuContentRef.current?.getBoundingClientRect();
                                if (!rect) return;
                                setFlyoutAnchor({
                                    top: rect.top,
                                    left: rect.left,
                                    right: rect.right,
                                });
                            }}
                        >
                            <FolderIcon className="size-4" />
                            <span className="min-w-0 flex-1 truncate">
                                {t("sidebar.moveToProject")}
                            </span>
                            {currentProject ? (
                                <span className="shrink-0 text-xs text-[#9C978A]">
                                    {currentProject.name}
                                </span>
                            ) : null}
                            <ChevronRightIcon className="size-3.5 shrink-0 text-[#9C978A]" />
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            className="text-[#B23B2E] data-highlighted:bg-[#FBEDEA] data-highlighted:text-[#B23B2E]"
                            onSelect={() => setConfirmDeleteOpen(true)}
                        >
                            <Trash2Icon className="size-4" />
                            {t("threadList.delete")}
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                    {flyoutAnchor ? (
                        <MoveToProjectFlyout
                            panelRef={flyoutRef}
                            anchorRect={flyoutAnchor}
                            projects={projects}
                            currentProjectId={thread.project_id}
                            onSelect={(projectId, name) => {
                                void onMove(projectId);
                                showToast(t("sidebar.movedToast", { project: name }));
                                closeAll();
                            }}
                            onRemove={(name) => {
                                void onMove(null);
                                showToast(t("sidebar.removedToast", { project: name }));
                                closeAll();
                            }}
                            onCreate={async (name) => {
                                const project = await onCreateProject(name);
                                if (!project) {
                                    return;
                                }
                                void onMove(project.id);
                                showToast(
                                    t("sidebar.movedToast", { project: project.name }),
                                );
                                closeAll();
                            }}
                            onClose={closeAll}
                        />
                    ) : null}
                </DropdownMenu>
            ) : null}
            <DeleteThreadDialog
                open={confirmDeleteOpen}
                onOpenChange={setConfirmDeleteOpen}
                onConfirm={() => {
                    void onDelete();
                    showToast(t("sidebar.deletedToast"));
                }}
            />
        </div>
    );
}

function ProjectRow({
    project,
    open,
    highlighted,
    disabled,
    onToggle,
    onNewThread,
    onRename,
    onDelete,
    children,
}: {
    project: SidebarProject;
    open: boolean;
    highlighted: boolean;
    disabled: boolean;
    onToggle: () => void;
    onNewThread: () => void;
    onRename: (name: string) => Promise<void> | void;
    onDelete: () => Promise<void> | void;
    children?: ReactNode;
}) {
    const { t } = useTranslation();
    const [renaming, setRenaming] = useState(false);
    const [name, setName] = useState(project.name);
    const [menuOpen, setMenuOpen] = useState(false);
    const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

    const saveRename = () => {
        const next = name.trim();
        setRenaming(false);
        if (!next || next === project.name) {
            setName(project.name);
            return;
        }
        void onRename(next);
    };

    return (
        <div className="group/project mb-0.5">
            <div
                className={cn(
                    "flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[13px] font-semibold transition-colors",
                    highlighted
                        ? "bg-[#EAF1F9] text-[#1D5FA8]"
                        : "text-[#201F1C] hover:bg-[#F0EEE7]",
                )}
            >
                <button
                    type="button"
                    aria-expanded={open}
                    onClick={onToggle}
                    className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
                >
                    <ChevronRightIcon
                        className={cn(
                            "size-3 shrink-0 text-[#9C978A] transition-transform",
                            open && "rotate-90",
                        )}
                    />
                    <FolderIcon className="size-[15px] shrink-0 text-[#1D5FA8]" />
                    {renaming ? (
                        <input
                            autoFocus
                            value={name}
                            onClick={(event) => event.stopPropagation()}
                            onChange={(event) => setName(event.target.value)}
                            onBlur={saveRename}
                            onKeyDown={(
                                event: KeyboardEvent<HTMLInputElement>,
                            ) => {
                                if (event.key === "Enter") saveRename();
                                if (event.key === "Escape") {
                                    setName(project.name);
                                    setRenaming(false);
                                }
                            }}
                            className="min-w-0 flex-1 rounded-[5px] border border-[#1D5FA8] bg-white px-1.5 py-0.5 text-[13px] font-normal text-[#201F1C] outline-none"
                        />
                    ) : (
                        <span className="truncate">{project.name}</span>
                    )}
                    {project.qualifier ? (
                        <span className="truncate text-[11px] font-normal text-[#9C978A]">
                            {project.qualifier}
                        </span>
                    ) : null}
                    <span className="ml-auto shrink-0 text-[11px] font-medium text-[#9C978A]">
                        {project.threads.length}
                    </span>
                </button>

                {!renaming ? (
                    <>
                        <button
                            type="button"
                            disabled={disabled}
                            onClick={onNewThread}
                            title={t("sidebar.newChatInProject")}
                            aria-label={t("sidebar.newChatInProject")}
                            className="project-add flex size-[22px] shrink-0 items-center justify-center rounded-md text-[#9C978A] opacity-0 hover:bg-[#E5E2D9] hover:text-[#201F1C] focus-visible:opacity-100 group-hover/project:opacity-100 disabled:cursor-not-allowed"
                        >
                            <PlusIcon className="size-3.5" />
                        </button>
                        <DropdownMenu
                            modal={false}
                            open={menuOpen}
                            onOpenChange={setMenuOpen}
                        >
                            <DropdownMenuTrigger asChild>
                                <button
                                    type="button"
                                    className="project-more flex size-[22px] shrink-0 items-center justify-center rounded-md text-[#9C978A] opacity-0 hover:bg-[#E5E2D9] hover:text-[#201F1C] focus-visible:opacity-100 data-[state=open]:opacity-100 group-hover/project:opacity-100"
                                    aria-label={t("sidebar.projectActions")}
                                >
                                    <MoreHorizontalIcon className="size-4" />
                                </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                                align="start"
                                side="right"
                                collisionPadding={12}
                                className="w-48 border-[#E4E1D9] bg-white"
                            >
                                <DropdownMenuItem
                                    onSelect={() => setRenaming(true)}
                                >
                                    <PencilIcon className="size-4" />
                                    {t("sidebar.renameProject")}
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem
                                    className="text-[#B23B2E] data-highlighted:bg-[#FBEDEA] data-highlighted:text-[#B23B2E]"
                                    onSelect={() => setConfirmDeleteOpen(true)}
                                >
                                    <Trash2Icon className="size-4" />
                                    {t("sidebar.deleteProject")}
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </>
                ) : null}
            </div>
            {open ? (
                <div className="ml-5 border-l border-[#E4E1D9] pl-3">
                    {children}
                    {project.threads.length === 0 && project.pinnedCount > 0 ? (
                        <div className="px-2 pb-2 pt-0.5 text-[12px] text-[#9C978A]">
                            {t("sidebar.projectAllPinned", {
                                count: project.pinnedCount,
                            })}
                        </div>
                    ) : null}
                </div>
            ) : null}
            <DeleteProjectDialog
                open={confirmDeleteOpen}
                onOpenChange={setConfirmDeleteOpen}
                onConfirm={() => void onDelete()}
            />
        </div>
    );
}

export function ThreadSidebar(props: ThreadSidebarProps) {
    const { t, i18n } = useTranslation();
    const groups = useMemo(
        () => groupThreads(props.threads, props.projects),
        [props.threads, props.projects],
    );
    // Pinned chats only: their row lives in Pinned, so the project highlight is
    // what shows the home. A regular chat is already visible inside its project.
    const activeThread = props.threads.find(
        (thread) => thread.id === props.activeThreadId,
    );
    const pinnedActiveProjectId = activeThread?.pinned
        ? (activeThread.project_id ?? null)
        : null;
    const [userOpenProjects, setUserOpenProjects] = useState<Set<string> | null>(
        () => storedOpenProjects(),
    );
    const openProjects = userOpenProjects ?? defaultOpenProjects(groups.projects);
    const [searchOpen, setSearchOpen] = useState(false);
    const [createProjectOpen, setCreateProjectOpen] = useState(false);
    const [query, setQuery] = useState("");
    const [toast, setToast] = useState<string | null>(null);
    const [collapsedSections, setCollapsedSections] = useState<Set<string>>(
        () => storedCollapsedSections(),
    );
    const [visibleOlderCount, setVisibleOlderCount] =
        useState(OLDER_PAGE_SIZE);
    const toggleSection = (key: string) => {
        setCollapsedSections((current) => {
            const next = new Set(current);
            if (next.has(key)) {
                next.delete(key);
            } else {
                next.add(key);
            }
            return next;
        });
    };
    const toastTimer = useRef<number | null>(null);

    const showToast = (message: string) => {
        setToast(message);
        if (toastTimer.current) window.clearTimeout(toastTimer.current);
        toastTimer.current = window.setTimeout(() => setToast(null), 1600);
    };

    useEffect(() => {
        const onKey = (event: globalThis.KeyboardEvent) => {
            if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
                event.preventDefault();
                setSearchOpen((open) => !open);
            }
            if (event.key === "Escape") setSearchOpen(false);
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, []);

    useEffect(() => {
        if (userOpenProjects) {
            writeStoredStringSet(OPEN_PROJECTS_KEY, userOpenProjects);
        }
    }, [userOpenProjects]);

    useEffect(() => {
        writeStoredStringSet(COLLAPSED_SECTIONS_KEY, collapsedSections);
    }, [collapsedSections]);

    const toggleProject = (key: string) => {
        const next = new Set(openProjects);
        if (next.has(key)) {
            next.delete(key);
        } else {
            next.add(key);
        }
        setUserOpenProjects(next);
    };

    const threadOrder = useMemo(() => orderedThreads(groups), [groups]);

    const allRows = (items: NovaThreadSummary[]) => items.map((thread) => (
        <ThreadRow
            key={thread.id}
            thread={thread}
            selected={thread.id === props.activeThreadId}
            running={thread.id === props.runningThreadId}
            projects={groups.projects}
            disabled={props.disabled}
            onSelect={() => props.onSelectThread(thread.id)}
            onRename={(title) => props.onRenameThread(thread.id, title)}
            onPin={(pinned) => props.onPinThread(thread.id, pinned)}
            onMove={(projectId) => props.onMoveThread(thread.id, projectId)}
            onDelete={() =>
                props.onDeleteThread(
                    thread.id,
                    nextThreadAfterDelete(threadOrder, thread.id),
                )
            }
            onCreateProject={props.onCreateProject}
            showToast={showToast}
        />
    ));

    const searchResults = query.trim()
        ? props.threads.filter((thread) => thread.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
        : props.threads.slice(0, 8);

    const groupMeta = (thread: NovaThreadSummary) => {
        const project = thread.project_id
            ? groups.projects.find((item) => item.id === thread.project_id)
            : undefined;
        if (project) {
            return project.name;
        }
        return t(`sidebar.date.${dateBucket(thread.updated_at)}`);
    };

    return (
        <aside className="flex h-screen w-(--sidebar-width) shrink-0 flex-col border-r border-[#E4E1D9] bg-[#FBFAF7] text-[#201F1C]">
            <div className="flex items-center justify-between px-3.5 pb-2.5 pt-4">
                <span className="text-[15px] font-bold tracking-[-0.01em]">Nova</span>
                <div className="flex gap-0.5">
                    <button type="button" title={t("sidebar.searchTitle")} onClick={() => setSearchOpen(true)} className="flex size-7 items-center justify-center rounded-[7px] text-[#6E6A60] hover:bg-[#EFEDE6] hover:text-[#201F1C]"><SearchIcon className="size-4" /></button>
                    <button type="button" aria-label={t("app.collapseSidebar")} onClick={props.onCollapse} className="flex size-7 items-center justify-center rounded-[7px] text-[#6E6A60] hover:bg-[#EFEDE6] hover:text-[#201F1C]"><PanelLeftCloseIcon className="size-4" /></button>
                </div>
            </div>
            <div className="px-3 pb-2.5">
                <button type="button" onClick={props.onNewThread} disabled={props.disabled} className="flex w-full items-center gap-2 rounded-[9px] border border-[#D6D2C7] bg-white px-3 py-2 text-[13.5px] font-medium hover:border-[#1D5FA8] hover:text-[#1D5FA8] disabled:opacity-50"><PlusIcon className="size-[15px]" />{t("threadList.newChat")}</button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
                <Section title={t("sidebar.pinned")} collapsed={collapsedSections.has("pinned")} onToggle={() => toggleSection("pinned")} empty={groups.pinned.length === 0 ? t("sidebar.noPinned") : null}>{allRows(groups.pinned)}</Section>
                <Section
                    title={t("sidebar.projects")}
                    collapsed={collapsedSections.has("projects")}
                    onToggle={() => toggleSection("projects")}
                    empty={
                        groups.projects.length === 0
                            ? t("sidebar.noProjects")
                            : null
                    }
                    actions={
                        <button
                            type="button"
                            disabled={props.disabled}
                            onClick={() => setCreateProjectOpen(true)}
                            title={t("sidebar.newProject")}
                            aria-label={t("sidebar.newProject")}
                            className="section-add flex size-[22px] items-center justify-center rounded-md text-[#9C978A] hover:bg-[#E5E2D9] hover:text-[#201F1C] disabled:cursor-not-allowed"
                        >
                            <PlusIcon className="size-3.5" />
                        </button>
                    }
                >
                    {groups.projects.map((project) => (
                        <ProjectRow
                            key={project.id}
                            project={project}
                            open={openProjects.has(project.id)}
                            highlighted={project.id === pinnedActiveProjectId}
                            disabled={props.disabled}
                            onToggle={() => toggleProject(project.id)}
                            onNewThread={() =>
                                props.onNewThreadInProject(project.id)
                            }
                            onRename={(name) =>
                                props.onRenameProject(project.id, name)
                            }
                            onDelete={() => props.onDeleteProject(project.id)}
                        >
                            {allRows(project.threads)}
                        </ProjectRow>
                    ))}
                </Section>
                <Section title={t("sidebar.chats")} collapsed={collapsedSections.has("chats")} onToggle={() => toggleSection("chats")}>
                    {DATE_BUCKETS.map((key) => {
                        const bucket = groups.chats[key];
                        if (!bucket.length) return null;
                        const visible =
                            key === "older"
                                ? bucket.slice(0, visibleOlderCount)
                                : bucket;
                        const hidden = bucket.length - visible.length;
                        return (
                            <Fragment key={key}>
                                <div className="px-2 pb-1 pt-2 text-[11px] font-semibold text-[#9C978A]">{t(`sidebar.date.${key}`)}</div>
                                {allRows(visible)}
                                {key === "older" && hidden > 0 ? (
                                    <button
                                        type="button"
                                        onClick={() =>
                                            setVisibleOlderCount(
                                                (count) => count + OLDER_PAGE_SIZE,
                                            )
                                        }
                                        className="mt-0.5 w-full rounded-lg px-2 py-1.5 text-left text-[12.5px] text-[#9C978A] hover:bg-[#F0EEE7] hover:text-[#201F1C]"
                                    >
                                        {t("sidebar.showMoreOlder", {
                                            count: Math.min(
                                                OLDER_PAGE_SIZE,
                                                hidden,
                                            ),
                                        })}
                                    </button>
                                ) : null}
                            </Fragment>
                        );
                    })}
                </Section>
            </div>
            <div className="border-t border-[#E4E1D9] p-2">
                <DropdownMenu>
                    <DropdownMenuTrigger asChild><button type="button" className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-[13.5px] text-[#6E6A60] hover:bg-[#F0EEE7] hover:text-[#201F1C]"><SettingsIcon className="size-4" />{t("sidebar.settings")}</button></DropdownMenuTrigger>
                    <DropdownMenuContent side="top" align="start" collisionPadding={12} className="w-64 border-[#E4E1D9] bg-white">
                        <DropdownMenuItem onSelect={props.onOpenMemory}><DatabaseIcon className="size-4" />{t("memory.manage")}</DropdownMenuItem>
                        <DropdownMenuSub>
                            <DropdownMenuSubTrigger>
                                <LanguagesIcon className="size-4" />
                                {t("sidebar.language")}
                                <span className="ml-auto text-xs text-[#9C978A]">{i18n.language === "zh-CN" ? "简体中文" : "English"}</span>
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent className="border-[#E4E1D9] bg-white">
                                <DropdownMenuItem onSelect={() => void i18n.changeLanguage("zh-CN")}>
                                    <CheckIcon className={cn("size-4", i18n.language !== "zh-CN" && "invisible")} />
                                    简体中文
                                </DropdownMenuItem>
                                <DropdownMenuItem onSelect={() => void i18n.changeLanguage("en")}>
                                    <CheckIcon className={cn("size-4", i18n.language !== "en" && "invisible")} />
                                    English
                                </DropdownMenuItem>
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>
                        <DropdownMenuSeparator />
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
            {searchOpen ? <div role="dialog" aria-modal="true" className="fixed inset-0 z-[70] flex items-start justify-center bg-[rgba(28,27,24,.32)] pt-[108px]" onMouseDown={(event) => event.target === event.currentTarget && setSearchOpen(false)}>
                <div className="flex max-h-[60vh] w-[560px] max-w-[90vw] flex-col overflow-hidden rounded-[13px] bg-white shadow-[0_24px_60px_rgba(0,0,0,.22)]">
                    <div className="flex items-center gap-2.5 border-b border-[#E4E1D9] px-4 py-3.5"><SearchIcon className="size-[17px] text-[#9C978A]" /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("sidebar.searchPlaceholder")} className="min-w-0 flex-1 bg-transparent text-[15px] outline-none" /><kbd className="rounded border border-[#D6D2C7] px-1.5 py-0.5 font-mono text-[11px] text-[#9C978A]">Esc</kbd></div>
                    <div className="overflow-y-auto p-1.5">{searchResults.length ? searchResults.map((thread) => <button key={thread.id} type="button" onClick={() => { props.onSelectThread(thread.id); setSearchOpen(false); }} className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13.5px] hover:bg-[#F0EEE7]"><MessageCircleIcon className="size-4 shrink-0 text-[#9C978A]" /><span className="min-w-0 flex-1 truncate"><HighlightedText text={thread.title} query={query.trim()} /></span><span className="shrink-0 text-[11px] text-[#9C978A]">{groupMeta(thread)}</span></button>) : <div className="px-4 py-6 text-center text-[13px] text-[#9C978A]">{t("sidebar.searchEmpty")}</div>}</div>
                </div>
            </div> : null}
            {toast ? <div className="fixed bottom-5 left-1/2 z-[80] -translate-x-1/2 rounded-full bg-[#201F1C] px-3.5 py-2 text-xs text-white">{toast}</div> : null}
            <CreateProjectDialog
                open={createProjectOpen}
                onOpenChange={setCreateProjectOpen}
                onCreate={async (name, path) => {
                    await props.onCreateProject(name, path);
                }}
            />
        </aside>
    );
}

function Section({
    title,
    empty,
    collapsed,
    onToggle,
    actions,
    children,
}: {
    title: string;
    empty?: string | null;
    collapsed: boolean;
    onToggle: () => void;
    actions?: ReactNode;
    children?: ReactNode;
}) {
    return (
        <section className="mb-1">
            <div className="group/section flex items-center gap-1 rounded-md px-2 pb-1 pt-3">
                <button
                    type="button"
                    aria-expanded={!collapsed}
                    onClick={onToggle}
                    className="flex min-w-0 flex-1 items-center gap-1 text-left text-[11.5px] font-semibold text-[#6E6A60] hover:text-[#201F1C]"
                >
                    <span>{title}</span>
                    <ChevronRightIcon
                        aria-hidden="true"
                        className={cn(
                            "section-chev size-3 shrink-0 opacity-0 transition-transform group-hover/section:opacity-100",
                            collapsed ? "rotate-0 opacity-100" : "rotate-90",
                        )}
                    />
                </button>
                {actions ? (
                    <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover/section:opacity-100">
                        {actions}
                    </div>
                ) : null}
            </div>
            {collapsed ? null : empty ? (
                <div className="px-2 pb-2.5 pt-0.5 text-[12px] text-[#9C978A]">
                    {empty}
                </div>
            ) : (
                children
            )}
        </section>
    );
}
