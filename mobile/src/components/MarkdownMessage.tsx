import React, { useMemo, type ReactNode } from "react";
import { StyleSheet, Text } from "react-native";
import { StreamdownRN } from "streamdown-rn";

import { markdownTheme, useTheme } from "../theme/useTheme";

class MarkdownBoundary extends React.Component<
    { fallback: ReactNode; children: ReactNode },
    { failed: boolean }
> {
    state = { failed: false };

    static getDerivedStateFromError(): { failed: boolean } {
        return { failed: true };
    }

    componentDidCatch(error: Error): void {
        console.warn("Markdown render failed", error);
    }

    render(): ReactNode {
        return this.state.failed ? this.props.fallback : this.props.children;
    }
}

export function MarkdownMessage({
    text,
    streaming = false,
}: {
    text: string;
    streaming?: boolean;
}) {
    const { theme } = useTheme();
    const mdTheme = useMemo(() => markdownTheme(theme), [theme]);

    if (!text) {
        return null;
    }

    return (
        <MarkdownBoundary
            key={mdTheme.colors.background}
            fallback={
                <Text style={[styles.fallback, { color: theme.foreground }]}>
                    {text}
                </Text>
            }
        >
            <StreamdownRN
                theme={mdTheme}
                isComplete={!streaming}
                style={styles.container}
            >
                {text}
            </StreamdownRN>
        </MarkdownBoundary>
    );
}

const styles = StyleSheet.create({
    container: {
        width: "100%",
    },
    fallback: {
        fontSize: 14,
        lineHeight: 22,
    },
});
