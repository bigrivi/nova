import { Platform, useColorScheme } from "react-native";

import { themeTokens, type Theme, type ThemeName } from "./tokens";

export type MarkdownThemeConfig = {
    colors: {
        background: string;
        foreground: string;
        muted: string;
        accent: string;
        codeBackground: string;
        codeForeground: string;
        border: string;
        link: string;
        syntaxDefault: string;
        syntaxKeyword: string;
        syntaxString: string;
        syntaxNumber: string;
        syntaxComment: string;
        syntaxFunction: string;
        syntaxClass: string;
        syntaxOperator: string;
    };
    fonts: {
        regular?: string;
        bold?: string;
        mono: string;
    };
    spacing: {
        block: number;
        inline: number;
        indent: number;
    };
};

export function useTheme(): { name: ThemeName; theme: Theme } {
    const scheme = useColorScheme();
    const name: ThemeName = scheme === "dark" ? "dark" : "light";
    return { name, theme: themeTokens(name) };
}

/** Map Nova's tokens onto the Markdown renderer's palette. */
export function markdownTheme(theme: Theme): MarkdownThemeConfig {
    return {
        colors: {
            background: theme.background,
            foreground: theme.foreground,
            muted: theme.mutedForeground,
            accent: theme.brand,
            codeBackground: theme.codeBg,
            codeForeground: theme.codeFg,
            border: theme.border,
            link: theme.brand,
            syntaxDefault: theme.codeFg,
            syntaxKeyword: theme.brand,
            syntaxString: theme.success,
            syntaxNumber: theme.warning,
            syntaxComment: theme.weakStrong,
            syntaxFunction: theme.brand,
            syntaxClass: theme.successStrong,
            syntaxOperator: theme.mutedForeground,
        },
        fonts: {
            mono:
                Platform.select({
                    ios: "Menlo",
                    android: "monospace",
                    default: "monospace",
                }) ?? "monospace",
        },
        spacing: { block: 10, inline: 4, indent: 16 },
    };
}
