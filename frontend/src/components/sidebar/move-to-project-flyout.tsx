"use client";

import { CheckIcon, FolderIcon, PlusIcon, SearchIcon } from "lucide-react";
import {
    useCallback,
    useEffect,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
    type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

import { HighlightedText } from "./highlight-text";
import type { SidebarProject } from "./sidebar-model";

const FLYOUT_WIDTH = 220;
const VIEWPORT_MARGIN = 8;

type AnchorRect = { top: number; left: number; right: number };

function horizontalLeft(anchor: AnchorRect): number {
    let left = anchor.right + 6;
    if (left + FLYOUT_WIDTH > window.innerWidth - VIEWPORT_MARGIN) {
        left = anchor.left - FLYOUT_WIDTH - 6;
    }
    return Math.max(left, VIEWPORT_MARGIN);
}

function clampTop(anchorTop: number, height: number): number {
    const maxTop = window.innerHeight - VIEWPORT_MARGIN - height;
    return Math.min(
        Math.max(anchorTop, VIEWPORT_MARGIN),
        Math.max(maxTop, VIEWPORT_MARGIN),
    );
}

export function MoveToProjectFlyout({
    panelRef,
    anchorRect,
    projects,
    currentProjectId,
    onSelect,
    onRemove,
    onCreate,
    onClose,
}: {
    panelRef: RefObject<HTMLDivElement | null>;
    anchorRect: AnchorRect;
    projects: SidebarProject[];
    currentProjectId: string | null;
    onSelect: (projectId: string, name: string) => void;
    onRemove: (name: string) => void;
    onCreate: (name: string) => Promise<void> | void;
    onClose: () => void;
}) {
    const { t } = useTranslation();
    const [query, setQuery] = useState("");
    const [position, setPosition] = useState(() => ({
        left: horizontalLeft(anchorRect),
        top: anchorRect.top,
    }));
    const inputRef = useRef<HTMLInputElement | null>(null);

    const recompute = useCallback(() => {
        const height = panelRef.current?.offsetHeight ?? 0;
        setPosition({
            left: horizontalLeft(anchorRect),
            top: clampTop(anchorRect.top, height),
        });
    }, [anchorRect, panelRef]);

    useEffect(() => {
        inputRef.current?.focus();
    }, []);

    useLayoutEffect(() => {
        recompute();
    }, [recompute, query]);

    useEffect(() => {
        window.addEventListener("resize", recompute);
        return () => window.removeEventListener("resize", recompute);
    }, [recompute]);

    useEffect(() => {
        const onPointerDown = (event: PointerEvent) => {
            if (panelRef.current?.contains(event.target as Node)) {
                return;
            }
            onClose();
        };
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                event.preventDefault();
                onClose();
            }
        };
        document.addEventListener("pointerdown", onPointerDown, true);
        window.addEventListener("keydown", onKeyDown);
        return () => {
            document.removeEventListener("pointerdown", onPointerDown, true);
            window.removeEventListener("keydown", onKeyDown);
        };
    }, [onClose, panelRef]);

    const matched = useMemo(() => {
        const needle = query.trim().toLocaleLowerCase();
        if (!needle) return projects;
        return projects.filter((project) =>
            project.name.toLocaleLowerCase().includes(needle),
        );
    }, [projects, query]);

    const currentProject = projects.find(
        (project) => project.id === currentProjectId,
    );
    const newProjectName = query.trim();

    return createPortal(
        <div
            ref={panelRef}
            className="fixed z-[70] w-[220px] overflow-hidden rounded-[10px] border border-[#E4E1D9] bg-white shadow-[0_12px_32px_rgba(0,0,0,.16)]"
            style={{ left: position.left, top: position.top }}
        >
            <div className="flex items-center gap-[7px] border-b border-[#E4E1D9] px-2.5 py-2">
                <SearchIcon className="size-3.5 shrink-0 text-[#9C978A]" />
                <input
                    ref={inputRef}
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder={t("sidebar.searchProjects")}
                    autoComplete="off"
                    className="min-w-0 flex-1 bg-transparent text-[13px] text-[#201F1C] outline-none"
                />
            </div>
            <div className="max-h-[208px] overflow-y-auto p-1.5">
                {matched.length === 0 && !newProjectName ? (
                    <div className="px-2.5 py-4 text-center text-[12.5px] text-[#9C978A]">
                        {t("sidebar.noMatchingProjects")}
                    </div>
                ) : (
                    matched.map((project) => {
                        const isCurrent = project.id === currentProjectId;
                        return (
                            <button
                                key={project.id}
                                type="button"
                                onClick={() => onSelect(project.id, project.name)}
                                className="flex w-full items-center gap-2 rounded-[7px] px-2 py-1.5 text-left text-[13px] text-[#201F1C] hover:bg-[#F0EEE7]"
                            >
                                <FolderIcon className="size-3.5 shrink-0 text-[#9C978A]" />
                                <span className="min-w-0 flex-1 truncate">
                                    <HighlightedText
                                        text={project.name}
                                        query={query}
                                    />
                                </span>
                                {isCurrent ? (
                                    <CheckIcon className="size-3.5 shrink-0 text-[#1D5FA8]" />
                                ) : null}
                            </button>
                        );
                    })
                )}
                {newProjectName ? (
                    <button
                        type="button"
                        onClick={() => void onCreate(newProjectName)}
                        className="flex w-full items-center gap-2 rounded-[7px] px-2 py-1.5 text-left text-[13px] text-[#1D5FA8] hover:bg-[#EAF1F9]"
                    >
                        <PlusIcon className="size-3.5 shrink-0" />
                        <span className="min-w-0 flex-1 truncate">
                            {t("sidebar.newProjectNamed", {
                                name: newProjectName,
                            })}
                        </span>
                    </button>
                ) : null}
            </div>
            {currentProject ? (
                <button
                    type="button"
                    onClick={() => onRemove(currentProject.name)}
                    className={cn(
                        "w-full border-t border-[#E4E1D9] px-2.5 py-2 text-left text-[13px] text-[#B23B2E]",
                        "hover:bg-[#FBEDEA]",
                    )}
                >
                    {t("sidebar.removeProjectNamed", {
                        project: currentProject.name,
                    })}
                </button>
            ) : null}
        </div>,
        document.body,
    );
}
