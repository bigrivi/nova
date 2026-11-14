/** One section of the session panel: a label, and whatever qualifies it. */
import { TextAttributes } from "@opentui/core";

import { useTheme } from "../../context/theme.tsx";

export function PanelHeading({
    label,
    detail,
}: {
    label: string;
    detail?: string;
}) {
    const theme = useTheme();
    return (
        <box flexDirection="row" gap={1} flexShrink={0}>
            <text
                fg={theme.text.base}
                attributes={TextAttributes.BOLD}
                content={label}
                wrapMode="none"
            />
            {detail ? (
                <text
                    fg={theme.text.muted}
                    content={detail}
                    wrapMode="none"
                />
            ) : null}
        </box>
    );
}
