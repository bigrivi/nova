/** Command suggestions dialog: shows matching slash commands and highlights the selected item
 * Always render the box and control it with visible — the OpenTUI reconciler does not support null children (it would corrupt the fibers of sibling components) */
import type { CommandSpec } from "../commands.ts";
import { theme } from "../theme.ts";

export function CommandSuggestions({
    items,
    selectedIndex,
}: {
    items: CommandSpec[];
    selectedIndex: number;
}) {
    return (
        <box
            visible={items.length > 0}
            flexDirection="column"
            flexShrink={0}
            paddingX={1}
            paddingY={1}
            border
            borderStyle="single"
            borderColor="#444c56"
        >
            {items.slice(0, 6).map((item, index) => (
                <text
                    key={item.id}
                    height={1}
                    fg={index === selectedIndex ? "#4f9cf9" : "#8b949e"}
                    content={`${index === selectedIndex ? "▸ " : "  "}${item.usage}  ${item.description}`}
                />
            ))}
            {items.length > 6 ? (
                <text height={1} fg={theme.muted} content="  …" />
            ) : null}
        </box>
    );
}
