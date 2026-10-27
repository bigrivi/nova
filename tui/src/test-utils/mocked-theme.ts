/** Complete stand-in for `context/theme.tsx`.
 *
 *  Bun module mocks are process-wide, so every suite that pins the palette must
 *  expose the whole facade — a partial mock breaks whichever suite imports the
 *  real module afterwards.
 */
import { darkTheme } from "../themes/index.ts";

export function mockedThemeModule() {
    return {
        useTheme: () => darkTheme,
        ThemeOverride: ({ children }: { children: unknown }) => children,
        useThemePreference: () => ({
            preference: "dark",
            setPreference: () => {},
            available: ["dark", "light"],
        }),
    };
}
