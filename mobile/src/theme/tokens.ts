/**
 * Chat presentation tokens, copied from the web theme.
 *
 * The values live in `frontend/src/index.css` (`:root` and `.dark`). Keeping
 * the same names here is what lets the phone and the web agree on what a
 * border, a muted surface, or the user bubble looks like. The web has a
 * `theme-tokens.test.ts` that requires both themes to define the same keys;
 * `tokens.test.ts` repeats that check for this copy.
 *
 * Strings stay as the platform values React Native wants: hex colours and
 * numeric spacing. Only tokens the chat surface actually uses are here.
 */

export type ThemeName = "light" | "dark";

export type Theme = {
    background: string;
    foreground: string;
    card: string;
    cardForeground: string;
    muted: string;
    mutedForeground: string;
    border: string;
    brand: string;
    brandSoft: string;
    onBrand: string;
    weak: string;
    weakStrong: string;
    userBubble: string;
    userBubbleBorder: string;
    codeBg: string;
    codeBorder: string;
    codeFg: string;
    danger: string;
    dangerSoft: string;
    success: string;
    warning: string;
    warningSoft: string;
    successSoft: string;
    successStrong: string;
    primary: string;
    primaryForeground: string;
    /** iOS shadow / Android elevation source; dark themes remove the lift. */
    composerShadow: {
        color: string;
        opacity: number;
        radius: number;
        offsetY: number;
    } | null;
    userBubbleShadow: {
        color: string;
        opacity: number;
        radius: number;
        offsetY: number;
    } | null;
};

const LIGHT: Theme = {
    background: "#F6F5F3",
    foreground: "#201F1C",
    card: "#FFFFFF",
    cardForeground: "#201F1C",
    muted: "#ECEAE4",
    mutedForeground: "#7A766F",
    border: "#E4E3DF",
    brand: "#1D5FA8",
    brandSoft: "#EAF1F9",
    onBrand: "#FFFFFF",
    weak: "#7A766F",
    weakStrong: "#6E6A60",
    userBubble: "#EEF1F6",
    userBubbleBorder: "#D9DFEA",
    codeBg: "#F6F5F2",
    codeBorder: "#F0EEE9",
    codeFg: "#201F1C",
    danger: "#B23B2E",
    dangerSoft: "#FBEDEA",
    success: "#17703F",
    warning: "#A5750F",
    warningSoft: "#F7EEDD",
    successSoft: "#E5F3EB",
    successStrong: "#157A4A",
    primary: "#201F1C",
    primaryForeground: "#FFFFFF",
    composerShadow: {
        color: "#141412",
        opacity: 0.04,
        radius: 24,
        offsetY: 4,
    },
    userBubbleShadow: {
        color: "#141412",
        opacity: 0.04,
        radius: 8,
        offsetY: 2,
    },
};

const DARK: Theme = {
    background: "#1C1B1A",
    foreground: "#E8E5E0",
    card: "#262524",
    cardForeground: "#E8E5E0",
    muted: "#2B2A25",
    mutedForeground: "#B4B0AA",
    border: "#2E2C2A",
    brand: "#7FA6F0",
    brandSoft: "#22304A",
    onBrand: "#1C1B18",
    weak: "#B4B0AA",
    weakStrong: "#938E86",
    userBubble: "#262A33",
    userBubbleBorder: "#343A46",
    codeBg: "#2A2826",
    codeBorder: "#37342F",
    codeFg: "#D9D5CF",
    danger: "#E8A0A0",
    dangerSoft: "#3A2320",
    success: "#6FCF97",
    warning: "#A5750F",
    warningSoft: "#F7EEDD",
    successSoft: "#E5F3EB",
    successStrong: "#157A4A",
    primary: "#E8E5E0",
    primaryForeground: "#1C1B18",
    composerShadow: null,
    userBubbleShadow: null,
};

export const themes: Record<ThemeName, Theme> = {
    light: LIGHT,
    dark: DARK,
};

export function themeTokens(name: ThemeName): Theme {
    return themes[name];
}

/**
 * Layout constants taken from the web chat surface.
 *
 * `threadMaxWidth` is the web's `--thread-max-width: 50rem`; the phone uses
 * the full width minus `gutterPhone`, and a tablet caps at this value.
 */
export const chatMetrics = {
    threadMaxWidth: 800,
    gutterPhone: 16,
    gutterTablet: 24,
    threadTopPadding: 24,
    messageGap: 8,
    messageGroupGap: 20,
    userBubbleRadius: 16,
    userBubblePaddingX: 16,
    userBubblePaddingY: 10,
    userBubbleMaxWidthRatio: 0.82,
    assistantAvatar: 24,
    assistantNameSize: 12,
    composerRadius: 20,
    composerPadding: 10,
    composerTextMinHeight: 40,
    composerTextMaxHeight: 160,
    composerFooterGap: 12,
    composerControlSize: 32,
    composerModelHeight: 32,
    contextRingSize: 28,
    attachmentTile: 56,
    composerImageTile: 96,
    cardRadius: 10,
    toolHeaderPaddingX: 12,
    toolHeaderPaddingY: 9,
    toolRowPaddingX: 12,
    toolRowPaddingY: 10,
    codeRadius: 8,
    codeHeaderPaddingX: 12,
    codeHeaderPaddingY: 6,
    codePadding: 12,
    bodySize: 14,
    bodyLineHeight: 22,
    metaSize: 12,
    monoSize: 12,
    toolNameSize: 12.5,
    disclaimerSize: 11,
    welcomeSize: 30,
    tapTarget: 44,
    scrollToBottomLift: 40,
} as const;

/** Web status-dot colours, shared by both themes exactly as the web does. */
export const toolStatusColors = {
    running: { background: "#F7EEDD", foreground: "#A5750F" },
    success: { background: "#E5F3EB", foreground: "#157A4A" },
} as const;
