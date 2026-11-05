import Feather from "@expo/vector-icons/Feather";
import { useEffect, useMemo, useState } from "react";
import {
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    TextInput,
    View,
} from "react-native";

import {
    isAnswerComplete,
    type AskQuestion,
} from "../chat/ask";
import { useTheme } from "../theme/useTheme";

function defaults(questions: readonly AskQuestion[]): Record<string, string> {
    const answers: Record<string, string> = {};
    for (const question of questions) {
        answers[question.id] = question.default;
    }
    return answers;
}

function splitSelection(value: string): string[] {
    return value
        .split(", ")
        .map((entry) => entry.trim())
        .filter(Boolean);
}

export function AskUserSheet({
    questions,
    onSubmit,
    onCancel,
}: {
    questions: AskQuestion[];
    onSubmit: (answers: Record<string, string>) => void;
    onCancel: () => void;
}) {
    const { theme } = useTheme();
    const signature = useMemo(
        () => questions.map((question) => question.id).join("|"),
        [questions],
    );
    const [answers, setAnswers] = useState<Record<string, string>>(() =>
        defaults(questions),
    );

    useEffect(() => {
        setAnswers(defaults(questions));
    }, [signature, questions]);

    const complete = isAnswerComplete(questions, answers);

    const setAnswer = (id: string, value: string) => {
        setAnswers((current) => ({ ...current, [id]: value }));
    };

    const toggleOption = (question: AskQuestion, label: string) => {
        const current = answers[question.id] ?? "";
        if (!question.multiple) {
            setAnswer(question.id, label);
            return;
        }
        const selected = splitSelection(current);
        const next = selected.includes(label)
            ? selected.filter((entry) => entry !== label)
            : [...selected, label];
        setAnswer(question.id, next.join(", "));
    };

    return (
        <View
            style={[
                styles.card,
                {
                    backgroundColor: theme.card,
                    borderColor: theme.brand,
                },
            ]}
        >
            <View style={styles.header}>
                <Feather name="help-circle" size={16} color={theme.brand} />
                <Text style={[styles.title, { color: theme.foreground }]}>
                    The agent needs an answer
                </Text>
                <Pressable
                    onPress={onCancel}
                    hitSlop={8}
                    accessibilityRole="button"
                    accessibilityLabel="Cancel questions"
                >
                    <Feather name="x" size={16} color={theme.weak} />
                </Pressable>
            </View>

            <ScrollView
                style={styles.scroll}
                keyboardShouldPersistTaps="handled"
                nestedScrollEnabled
            >
                {questions.map((question) => (
                    <View key={question.id} style={styles.question}>
                        {question.header ? (
                            <Text
                                style={[
                                    styles.questionHeader,
                                    { color: theme.weak },
                                ]}
                            >
                                {question.header}
                            </Text>
                        ) : null}
                        <Text
                            style={[
                                styles.questionText,
                                { color: theme.foreground },
                            ]}
                        >
                            {question.question}
                        </Text>

                        {question.inputType === "select" ? (
                            <View style={styles.options}>
                                {question.options.map((option) => {
                                    const selected = splitSelection(
                                        answers[question.id] ?? "",
                                    ).includes(option.label);
                                    return (
                                        <Pressable
                                            key={option.label}
                                            onPress={() =>
                                                toggleOption(
                                                    question,
                                                    option.label,
                                                )
                                            }
                                            style={[
                                                styles.option,
                                                {
                                                    borderColor: selected
                                                        ? theme.brand
                                                        : theme.border,
                                                    backgroundColor: selected
                                                        ? theme.brandSoft
                                                        : "transparent",
                                                },
                                            ]}
                                            accessibilityRole="radio"
                                            accessibilityState={{ selected }}
                                        >
                                            <Text
                                                style={[
                                                    styles.optionText,
                                                    {
                                                        color: selected
                                                            ? theme.brand
                                                            : theme.weakStrong,
                                                    },
                                                ]}
                                            >
                                                {option.label}
                                            </Text>
                                            {option.description ? (
                                                <Text
                                                    style={[
                                                        styles.optionDescription,
                                                        { color: theme.weak },
                                                    ]}
                                                >
                                                    {option.description}
                                                </Text>
                                            ) : null}
                                        </Pressable>
                                    );
                                })}
                            </View>
                        ) : (
                            <TextInput
                                value={answers[question.id] ?? ""}
                                onChangeText={(value) =>
                                    setAnswer(question.id, value)
                                }
                                multiline={question.inputType === "textarea"}
                                placeholder="Your answer"
                                placeholderTextColor={theme.weakStrong}
                                style={[
                                    styles.input,
                                    {
                                        color: theme.foreground,
                                        borderColor: theme.border,
                                        backgroundColor: theme.muted,
                                        minHeight:
                                            question.inputType === "textarea"
                                                ? 72
                                                : 40,
                                    },
                                ]}
                                textAlignVertical={
                                    question.inputType === "textarea"
                                        ? "top"
                                        : "center"
                                }
                            />
                        )}
                    </View>
                ))}
            </ScrollView>

            <View style={styles.actions}>
                <Pressable
                    onPress={onCancel}
                    style={[styles.button, { borderColor: theme.border }]}
                    accessibilityRole="button"
                >
                    <Text style={[styles.buttonText, { color: theme.weakStrong }]}>
                        Cancel
                    </Text>
                </Pressable>
                <Pressable
                    onPress={() => onSubmit(answers)}
                    disabled={!complete}
                    style={[
                        styles.button,
                        {
                            backgroundColor: complete
                                ? theme.primary
                                : theme.muted,
                            borderColor: "transparent",
                        },
                    ]}
                    accessibilityRole="button"
                >
                    <Text
                        style={[
                            styles.buttonText,
                            {
                                color: complete
                                    ? theme.primaryForeground
                                    : theme.weak,
                            },
                        ]}
                    >
                        Submit
                    </Text>
                </Pressable>
            </View>
        </View>
    );
}

const styles = StyleSheet.create({
    card: {
        borderRadius: 12,
        borderWidth: StyleSheet.hairlineWidth,
        padding: 12,
        gap: 10,
    },
    header: {
        flexDirection: "row",
        alignItems: "center",
        gap: 7,
    },
    title: {
        flex: 1,
        fontSize: 13.5,
        fontWeight: "700",
    },
    scroll: {
        maxHeight: 320,
    },
    question: {
        gap: 7,
        paddingVertical: 6,
    },
    questionHeader: {
        fontSize: 11,
        fontWeight: "600",
        textTransform: "uppercase",
        letterSpacing: 0.4,
    },
    questionText: {
        fontSize: 13.5,
        lineHeight: 19,
    },
    options: {
        gap: 6,
    },
    option: {
        borderRadius: 8,
        borderWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 10,
        paddingVertical: 8,
        gap: 2,
    },
    optionText: {
        fontSize: 12.5,
        fontWeight: "500",
    },
    optionDescription: {
        fontSize: 11,
        lineHeight: 15,
    },
    input: {
        borderRadius: 8,
        borderWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 10,
        paddingVertical: 8,
        fontSize: 13.5,
    },
    actions: {
        flexDirection: "row",
        justifyContent: "flex-end",
        gap: 8,
    },
    button: {
        minWidth: 84,
        height: 36,
        borderRadius: 9,
        borderWidth: StyleSheet.hairlineWidth,
        alignItems: "center",
        justifyContent: "center",
        paddingHorizontal: 14,
    },
    buttonText: {
        fontSize: 13,
        fontWeight: "600",
    },
});
