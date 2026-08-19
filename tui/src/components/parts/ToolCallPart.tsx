/** Tool call part: routes to ToolBlock */
import type { ToolCallPart as ToolCallPartData } from "../../stores/chat-store.ts";
import { ToolBlock } from "../ToolBlock.tsx";

export function ToolCallPartView({ part }: { part: ToolCallPartData }) {
    return <ToolBlock part={part} />;
}
