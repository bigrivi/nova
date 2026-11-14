/** Pick a code block from a message and copy it. */
import { useRenderer } from "@opentui/react";

import { useScreenStore } from "../../stores/screen-store.ts";
import { useToastStore } from "../../stores/toast-store.ts";
import { SearchableList } from "./SearchableList.tsx";

type CopyCodeBlockScreenProps = {
    blocks: string[];
};

export function CopyCodeBlockScreen({ blocks }: CopyCodeBlockScreenProps) {
    const renderer = useRenderer();

    return (
        <SearchableList
            title="Copy a code block"
            items={blocks.map((code, index) => ({
                label: `Block ${index + 1}  ·  ${firstLine(code)}`,
                value: String(index),
            }))}
            onSelect={(value) => {
                const code = blocks[Number(value)];
                if (code === undefined) return;
                const ok = renderer.copyToClipboardOSC52(code);
                if (ok) {
                    useToastStore.getState().show("Copied code block", 2000);
                }
                useScreenStore.getState().close();
            }}
            onClose={() => useScreenStore.getState().close()}
            emptyText="no code blocks"
        />
    );
}

function firstLine(code: string): string {
    const line = code.split("\n").find((entry) => entry.trim()) ?? "";
    return line.trim().slice(0, 48);
}
