/** One row of the status bar: content flush left, content flush right. */
import type { ReactNode } from "react";

export function StatusLine({
    left,
    right,
}: {
    left: ReactNode;
    right: ReactNode;
}) {
    return (
        <box
            flexDirection="row"
            width="100%"
            justifyContent="space-between"
            alignItems="center"
            flexShrink={0}
            gap={2}
        >
            <box
                flexDirection="row"
                alignItems="center"
                flexShrink={1}
                minWidth={0}
                gap={1}
            >
                {left}
            </box>
            <box
                flexDirection="row"
                alignItems="center"
                flexShrink={0}
                gap={1}
            >
                {right}
            </box>
        </box>
    );
}
