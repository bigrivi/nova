import { Platform, StyleSheet, Text, View } from "react-native";

import {
    countDiffLines,
    type ToolView,
} from "../chat/tool-view";
import type { ToolPart } from "../state/chat";
import { useTasks } from "../state/tasks";
import { chatMetrics } from "../theme/tokens";
import { useTheme } from "../theme/useTheme";

export const mono =
    Platform.select({
        ios: "Menlo",
        android: "monospace",
        default: "monospace",
    }) ?? "monospace";

const DIFF_ADD = { background: "#052E1E", color: "#86EFAC" };
const DIFF_DEL = { background: "#3B0A16", color: "#FDA4AF" };
const DIFF_HEADER = { background: "#0B2536", color: "#7DD3FC" };
const DIFF_CONTEXT = { background: "transparent", color: "#CBD5E1" };

function diffStyle(line: string): { background: string; color: string } {
    if (line.startsWith("--- ") || line.startsWith("+++ ")) {
        return DIFF_HEADER;
    }
    if (line.startsWith("@@")) {
        return DIFF_HEADER;
    }
    if (line.startsWith("+")) {
        return DIFF_ADD;
    }
    if (line.startsWith("-")) {
        return DIFF_DEL;
    }
    return DIFF_CONTEXT;
}

function BackgroundChip({ taskId }: { taskId: string }) {
    const { theme } = useTheme();
    const task = useTasks((state) => state.byId[taskId]);
    return (
        <View style={[styles.chip, { backgroundColor: theme.brandSoft }]}>
            <Text style={[styles.chipText, { color: theme.brand }]}>
                background
            </Text>
            <Text style={[styles.chipText, { color: theme.weak }]}>
                {task?.status ?? "running"}
            </Text>
        </View>
    );
}

export function ToolViewHeaderMeta({ view }: { view: ToolView }) {
    const { theme } = useTheme();

    if (view.kind === "file-mutation") {
        if (!view.diff) {
            return null;
        }
        const { added, removed } = countDiffLines(view.diff);
        return (
            <Text numberOfLines={1} style={styles.headerMeta}>
                <Text style={{ color: theme.success }}>+{added}</Text>
                <Text style={{ color: theme.weak }}> </Text>
                <Text style={{ color: theme.danger }}>−{removed}</Text>
            </Text>
        );
    }

    if (view.kind === "code-run") {
        return (
            <>
                {view.summary ? (
                    <Text
                        numberOfLines={1}
                        style={[styles.headerSummary, { color: theme.weak }]}
                    >
                        {view.summary}
                    </Text>
                ) : null}
                {view.backgroundTaskId ? (
                    <BackgroundChip taskId={view.backgroundTaskId} />
                ) : null}
            </>
        );
    }

    return null;
}

function PathText({ path }: { path: string }) {
    const { theme } = useTheme();
    return (
        <Text selectable style={[styles.path, { color: theme.brand }]}>
            {path}
        </Text>
    );
}

function DiffBlock({ diff }: { diff: string }) {
    return (
        <View style={styles.darkBlock}>
            {diff.split("\n").map((line, index) => {
                const tone = diffStyle(line);
                return (
                    <View
                        key={index}
                        style={{ backgroundColor: tone.background }}
                    >
                        <Text
                            selectable
                            style={[styles.diffLine, { color: tone.color }]}
                        >
                            {line || " "}
                        </Text>
                    </View>
                );
            })}
        </View>
    );
}

function ErrorText({ error }: { error: string }) {
    const { theme } = useTheme();
    return (
        <Text selectable style={[styles.error, { color: theme.danger }]}>
            {error}
        </Text>
    );
}

function ResultLabel() {
    const { theme } = useTheme();
    return (
        <Text
            style={[
                styles.bodyLabel,
                styles.resultLabel,
                { color: theme.foreground },
            ]}
        >
            Result
        </Text>
    );
}

function FileMutationBody({
    part,
    view,
}: {
    part: ToolPart;
    view: Extract<ToolView, { kind: "file-mutation" }>;
}) {
    const { theme } = useTheme();
    return (
        <View style={styles.stack}>
            {part.error ? <ErrorText error={part.error} /> : null}
            {view.path ? <PathText path={view.path} /> : null}
            {!part.error && view.headline ? (
                <Text
                    selectable
                    style={[styles.headline, { color: theme.foreground }]}
                >
                    {view.headline}
                </Text>
            ) : null}
            {!part.error && view.diff ? <DiffBlock diff={view.diff} /> : null}
            {!part.error && !view.diff && view.plain ? (
                <View
                    style={[
                        styles.plainBlock,
                        {
                            backgroundColor: theme.card,
                            borderColor: theme.border,
                        },
                    ]}
                >
                    <Text
                        selectable
                        style={[styles.plainText, { color: theme.weakStrong }]}
                    >
                        {view.plain}
                    </Text>
                </View>
            ) : null}
        </View>
    );
}

function CodeRunBody({
    part,
    view,
}: {
    part: ToolPart;
    view: Extract<ToolView, { kind: "code-run" }>;
}) {
    const { theme } = useTheme();
    return (
        <View style={styles.stack}>
            {part.error ? <ErrorText error={part.error} /> : null}
            {view.code ? (
                <View style={styles.darkBlock}>
                    <Text selectable style={styles.code}>
                        {view.code}
                    </Text>
                </View>
            ) : null}
            {view.output ? (
                <>
                    <ResultLabel />
                    <Text
                        selectable
                        style={[
                            styles.outputText,
                            { color: theme.weakStrong },
                        ]}
                    >
                        {view.output}
                    </Text>
                </>
            ) : null}
        </View>
    );
}

function DelegateBody({
    part,
    view,
}: {
    part: ToolPart;
    view: Extract<ToolView, { kind: "delegate" }>;
}) {
    const { theme } = useTheme();
    return (
        <View style={styles.stack}>
            {part.error ? <ErrorText error={part.error} /> : null}
            {view.task ? (
                <Text
                    selectable
                    style={[styles.headline, { color: theme.foreground }]}
                >
                    {view.task}
                </Text>
            ) : null}
            {part.status === "running" ? (
                <Text style={[styles.hint, { color: theme.weak }]}>
                    Sub-agent is working…
                </Text>
            ) : null}
            {view.output ? (
                <>
                    <ResultLabel />
                    <Text
                        selectable
                        style={[styles.prose, { color: theme.weakStrong }]}
                    >
                        {view.output}
                    </Text>
                </>
            ) : null}
        </View>
    );
}

export function ToolViewBody({
    part,
    view,
}: {
    part: ToolPart;
    view: ToolView;
}) {
    if (view.kind === "file-mutation") {
        return <FileMutationBody part={part} view={view} />;
    }
    if (view.kind === "code-run") {
        return <CodeRunBody part={part} view={view} />;
    }
    return <DelegateBody part={part} view={view} />;
}

const styles = StyleSheet.create({
    stack: {
        gap: 8,
    },
    headerMeta: {
        flex: 1,
        fontSize: 12,
    },
    headerSummary: {
        flex: 1,
        fontSize: 12,
    },
    chip: {
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        borderRadius: 6,
        paddingHorizontal: 6,
        paddingVertical: 2,
    },
    chipText: {
        fontSize: 10.5,
        fontWeight: "600",
    },
    path: {
        fontFamily: mono,
        fontSize: 12,
        lineHeight: 18,
    },
    headline: {
        fontSize: 13.5,
        lineHeight: 20,
    },
    darkBlock: {
        backgroundColor: "#020617",
        borderColor: "#1E293B",
        borderWidth: StyleSheet.hairlineWidth,
        borderRadius: chatMetrics.codeRadius,
        overflow: "hidden",
        paddingVertical: 6,
    },
    diffLine: {
        fontFamily: mono,
        fontSize: 11.5,
        lineHeight: 17,
        paddingHorizontal: 10,
        paddingVertical: 1,
    },
    code: {
        fontFamily: mono,
        fontSize: 12,
        lineHeight: 19,
        color: "#E2E8F0",
        paddingHorizontal: 10,
    },
    outputText: {
        fontFamily: mono,
        fontSize: 12,
        lineHeight: 19,
    },
    plainBlock: {
        borderRadius: chatMetrics.codeRadius,
        borderWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 10,
        paddingVertical: 8,
    },
    plainText: {
        fontFamily: mono,
        fontSize: 12,
        lineHeight: 19,
    },
    bodyLabel: {
        fontSize: 11,
        fontWeight: "700",
        marginBottom: 4,
    },
    resultLabel: {
        marginTop: 2,
    },
    error: {
        fontSize: 12.5,
        lineHeight: 19,
    },
    hint: {
        fontSize: 12,
    },
    prose: {
        fontSize: 13.5,
        lineHeight: 20,
    },
});
