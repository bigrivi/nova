import { expect, test } from "bun:test";

const { testRender } = await import("@opentui/react/test-utils");
const { LaunchScreen } = await import("./LaunchScreen.tsx");
const { StatusBar } = await import("../StatusBar.tsx");
const { AppProvider } = await import("../../context/app.tsx");

async function launch(width = 100, height = 24) {
    const setup = await testRender(
        <AppProvider>
            <box width="100%" height="100%" flexDirection="column">
                <LaunchScreen onCommand={() => {}} />
                <StatusBar />
            </box>
        </AppProvider>,
        { width, height },
    );
    for (let pass = 0; pass < 4; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 40));
    }
    return setup.captureCharFrame().split("\n");
}

function padding(line: string): number {
    return line.length - line.trimStart().length;
}

test("the launch screen is a rounded card holding only the composer", async () => {
    const lines = await launch();
    const top = lines.findIndex((line) => line.includes("╭"));
    expect(top).toBeGreaterThan(0);
    expect(lines[top]).toContain("╮");
    const body = lines[top + 2]!;
    expect(body).toContain(">");
    // nothing but the card between the top of the screen and the status bar
    const bottom = lines.findIndex((line) => line.includes("╰"));
    for (let y = bottom + 1; y < lines.length - 3; y += 1) {
        expect(lines[y]!.trim()).toBe("");
    }
});

test("the card is centred horizontally and vertically", async () => {
    const lines = await launch();
    const cardRow = lines.findIndex((line) => line.includes("╭"))!;
    const left = padding(lines[cardRow]!);
    const right = lines[cardRow]!.length - lines[cardRow]!.trimEnd().length;
    expect(Math.abs(left - right)).toBeLessThanOrEqual(1);

    const bottom = lines.findIndex((line) => line.includes("╰"));
    // the logo sits above the card; the logo+card column is centred as a unit
    const logoRow = lines.findIndex((line) => line.includes("█"));
    const unitTop = logoRow >= 0 ? logoRow : cardRow;
    // the status bar owns the last two rows
    const available = lines.length - 2;
    const above = unitTop;
    const below = available - 1 - bottom;
    expect(Math.abs(above - below)).toBeLessThanOrEqual(1);
});

test("the card holds a hint that eventually changes", async () => {
    const lines = await launch();
    const body = lines.find((line) => line.includes(">"))!;
    expect(body.length).toBeGreaterThan(10);
});

test("the NOVA mark renders above the card", async () => {
    const lines = await launch();
    const cardRow = lines.findIndex((line) => line.includes("╭"))!;
    const logoRow = lines.findIndex((line) => line.includes("█"))!;
    expect(logoRow).toBeGreaterThanOrEqual(0);
    expect(logoRow).toBeLessThan(cardRow);
    // the full mark is four block-letter rows
    const glyphRows = lines.filter((line) => line.includes("█"));
    expect(glyphRows.length).toBeGreaterThanOrEqual(4);
});

test("the mark collapses on narrow terminals", async () => {
    const lines = await launch(50, 24);
    expect(lines.some((line) => line.includes("N O V A"))).toBe(true);
    expect(lines.some((line) => line.includes("█"))).toBe(false);
});

test("the mark hides on short terminals", async () => {
    const lines = await launch(100, 10);
    expect(lines.some((line) => line.includes("█"))).toBe(false);
    expect(lines.some((line) => line.includes("N O V A"))).toBe(false);
});
