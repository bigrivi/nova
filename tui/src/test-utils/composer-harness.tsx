/** Test harness: the composer plus the root-painted menu, as the app wires them.
 *
 *  The menu is no longer rendered by the composer (see MenuOverlay), so a test
 *  that renders the composer alone cannot see it. Keeping the wiring in one place
 *  stops the two test files from drifting on how the pieces are assembled.
 */
import { useMenuStore } from "../stores/menu-store.ts";
import { Composer } from "../components/Composer.tsx";
import { MenuOverlay } from "../components/MenuOverlay.tsx";

export function ComposerShell({
    variant = "bar",
    height = 24,
    onCommand = () => {},
}: {
    variant?: "bar" | "card";
    height?: number;
    onCommand?: (id: string, args: string) => void;
}) {
    const anchor = useMenuStore((state) => state.anchor);
    return (
        <box
            flexDirection="column"
            width="100%"
            height={height}
            justifyContent="flex-end"
        >
            <Composer onCommand={onCommand} variant={variant} />
            <MenuOverlay
                anchorY={anchor.y}
                anchorX={anchor.x}
                anchorWidth={anchor.width}
                anchorEdgeY={anchor.edgeY}
            />
        </box>
    );
}
