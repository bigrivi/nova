export function firstLine(text: string, max: number): string {
    const line = text.split(/\r?\n/, 1)[0]?.replace(/\s+/g, " ").trim() ?? "";
    if (!line) {
        return "New session";
    }
    return line.length > max ? `${line.slice(0, Math.max(1, max - 1))}…` : line;
}
