import { expect, mock, test } from "bun:test";
import { contrastRatio } from "../../themes/contrast.ts";
import { darkTheme } from "../../themes/index.ts";
import { mockedThemeModule } from "../../test-utils/mocked-theme.ts";

mock.module("../../context/theme.tsx", mockedThemeModule);

const { testRender } = await import("@opentui/react/test-utils");
const { MouseButtons } = await import("@opentui/core/testing");
const { act } = await import("react");
const { SearchableList } = await import("./SearchableList.tsx");

const ITEMS = Array.from({ length: 20 }, (_, i) => ({
    label: `model-${i}`,
    value: `model-${i}`,
}));
const GROUPED = [
    { label: "model-a", value: "a", group: "OpenAI" },
    { label: "model-b", value: "b", group: "OpenAI" },
    { label: "model-c", value: "c", group: "Anthropic" },
];
const WIDTH = 60;
const HEIGHT = 24;

type SpanLines = {
    lines: {
        spans: {
            text: string;
            attributes: number;
            fg: { buffer: Uint16Array };
            bg: { buffer: Uint16Array };
        }[];
    }[];
};

/** RGB channels of a `#rrggbb` theme colour. */
function rgbOf(hex: string): number[] {
    return [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16));
}

/** The span that draws *text* on row `y`. */
function spanAt(spans: SpanLines, y: number, text: string) {
    return spans.lines[y]!.spans.find((span) => span.text.includes(text));
}

/** Whether row `y` carries the dark theme accent as its background. */
function rowBanded(spans: SpanLines, y: number): boolean {
    return spans.lines[y]!.spans.some(
        (span) =>
            span.bg.buffer[0] === 88 &&
            span.bg.buffer[1] === 166 &&
            span.bg.buffer[2] === 255,
    );
}

function rowY(frame: string, text: string): number {
    const y = frame.split("\n").findIndex((line) => line.includes(text));
    if (y < 0) throw new Error(`row not found: ${text}`);
    return y;
}

async function render(
    props: Partial<Parameters<typeof SearchableList>[0]> = {},
) {
    const setup = await testRender(
        <SearchableList
            title="Models"
            items={ITEMS}
            onSelect={() => {}}
            onClose={() => {}}
            {...props}
        />,
        { width: WIDTH, height: HEIGHT },
    );
    await setup.flush();
    return setup;
}

test("the mouse wheel scrolls the list", async () => {
    const setup = await render();
    const before = setup.captureCharFrame();
    const y = rowY(before, "model-5");
    await act(async () => {
        await setup.mockMouse.scroll(20, y, "down");
    });
    await setup.flush();
    const after = setup.captureCharFrame();
    expect(after).not.toBe(before);
    expect(after).toContain("model-12");
});

test("hovering bands the row with the accent, the current row stays unbanded", async () => {
    const setup = await render({ defaultValue: "model-3" });
    const frame = setup.captureCharFrame();
    const hoverY = rowY(frame, "model-1");
    const currentY = rowY(frame, "model-3");
    await act(async () => {
        await setup.mockMouse.moveTo(20, hoverY);
    });
    await setup.flush();
    const spans = setup.captureSpans();
    expect(rowBanded(spans, hoverY)).toBe(true);
    expect(rowBanded(spans, currentY)).toBe(false);
});

test("clicking a row submits it", async () => {
    let picked = "";
    const setup = await testRender(
        <SearchableList
            title="Models"
            items={ITEMS}
            onSelect={(value) => {
                picked = value;
            }}
            onClose={() => {}}
        />,
        { width: WIDTH, height: HEIGHT },
    );
    await setup.flush();
    const y = rowY(setup.captureCharFrame(), "model-5");
    await act(async () => {
        await setup.mockMouse.click(20, y);
    });
    await setup.flush();
    expect(picked).toBe("model-5");
});

test("renderLabel owns the row text while the label stays the search text", async () => {
    const setup = await testRender(
        <SearchableList
            title="Sessions"
            items={[{ label: "note", value: "1", updatedAt: "5m ago" }]}
            renderLabel={(item) => `${item.label}  —  ${item.updatedAt}`}
            onSelect={() => {}}
            onClose={() => {}}
        />,
        { width: WIDTH, height: HEIGHT },
    );
    await setup.flush();
    expect(setup.captureCharFrame()).toContain("note  —  5m ago");
});

test("a right click does not submit the row", async () => {
    let picked = "";
    const setup = await testRender(
        <SearchableList
            title="Models"
            items={ITEMS}
            onSelect={(value) => {
                picked = value;
            }}
            onClose={() => {}}
        />,
        { width: WIDTH, height: HEIGHT },
    );
    await setup.flush();
    const y = rowY(setup.captureCharFrame(), "model-5");
    await act(async () => {
        await setup.mockMouse.click(20, y, MouseButtons.RIGHT);
    });
    await setup.flush();
    expect(picked).toBe("");
});

test("the panel sits in the middle at any terminal height", async () => {
    const height = 40;
    const setup = await testRender(
        <SearchableList
            title="Models"
            items={ITEMS}
            onSelect={() => {}}
            onClose={() => {}}
        />,
        { width: WIDTH, height },
    );
    await setup.flush();
    const lines = setup.captureCharFrame().split("\n");
    const top = lines.findIndex((line) => line.includes("Models"));
    const bottom = lines.findLastIndex((line) => line.includes("↑↓ "));
    expect(Math.abs(top - (height - 1 - bottom))).toBeLessThanOrEqual(1);
});

test("only the current item is marked, and hover does not move the mark", async () => {
    const setup = await render({ defaultValue: "model-3" });
    const hoverY = rowY(setup.captureCharFrame(), "model-1");
    await act(async () => {
        await setup.mockMouse.moveTo(20, hoverY);
    });
    await setup.flush();
    const lines = setup.captureCharFrame().split("\n");
    const hovered = lines[rowY(lines.join("\n"), "model-1")];
    const current = lines[rowY(lines.join("\n"), "model-3")];
    expect(hovered).not.toContain("●");
    expect(current).toContain("●");
});


test("group headers line up with the item labels", async () => {
    const setup = await testRender(
        <SearchableList
            title="Models"
            items={GROUPED}
            onSelect={() => {}}
            onClose={() => {}}
        />,
        { width: WIDTH, height: HEIGHT },
    );
    await setup.flush();
    const lines = setup.captureCharFrame().split("\n");
    const frame = lines.join("\n");
    const header = lines[rowY(frame, "OpenAI")]!;
    const item = lines[rowY(frame, "model-a")]!;
    expect(header.indexOf("OpenAI")).toBe(item.indexOf("model-a"));
});

test("the row text stays readable on the accent band when hovered", async () => {
    const setup = await render({ items: GROUPED, defaultValue: "a" });
    const y = rowY(setup.captureCharFrame(), "model-a");
    await act(async () => {
        await setup.mockMouse.moveTo(20, y);
    });
    await setup.flush();
    const dot = spanAt(setup.captureSpans(), y, "●");
    expect(dot).toBeDefined();
    const band = Array.from(dot!.bg.buffer).slice(0, 3);
    const ink = Array.from(dot!.fg.buffer).slice(0, 3);
    expect(band).toEqual(rgbOf(darkTheme.accent));
    // the paired token, not a per-render guess
    expect(ink).toEqual(rgbOf(darkTheme.accentForeground));
    expect(
        contrastRatio(darkTheme.accentForeground, darkTheme.accent),
    ).toBeGreaterThan(4);
});

test("items read in the foreground colour", async () => {
    const setup = await testRender(
        <SearchableList
            title="Models"
            items={GROUPED}
            onSelect={() => {}}
            onClose={() => {}}
        />,
        { width: WIDTH, height: HEIGHT },
    );
    await setup.flush();
    const spans = setup.captureSpans();
    const frame = setup.captureCharFrame();
    const lines = frame.split("\n");
    // Row 0 is the cursor; check a row that is neither cursor nor current.
    expect(
        Array.from(
            spanAt(spans, rowY(frame, "model-b"), "model-b")!.fg.buffer,
        ).slice(0, 3),
    ).toEqual(rgbOf(darkTheme.foreground));
    expect(
        Array.from(spanAt(spans, rowY(frame, "OpenAI"), "OpenAI")!.fg.buffer).slice(0, 3),
    ).toEqual(rgbOf(darkTheme.accentText));
    expect(lines.length).toBeGreaterThan(0);
});

test("the filter input starts on the same column as the item labels", async () => {
    const setup = await testRender(
        <SearchableList
            title="Models"
            items={GROUPED}
            onSelect={() => {}}
            onClose={() => {}}
        />,
        { width: WIDTH, height: HEIGHT },
    );
    await setup.flush();
    const lines = setup.captureCharFrame().split("\n");
    const frame = lines.join("\n");
    const input = lines[rowY(frame, "Filter…")]!;
    const item = lines[rowY(frame, "model-b")]!;
    expect(input.indexOf("Filter…")).toBe(item.indexOf("model-b"));
});





test("the list shrinks to its content and caps at the viewport", async () => {
    const render = async (items: typeof ITEMS | typeof GROUPED) => {
        const setup = await testRender(
            <SearchableList
                title="Models"
                items={items}
                onSelect={() => {}}
                onClose={() => {}}
            />,
            { width: WIDTH, height: HEIGHT },
        );
        await setup.flush();
        const frame = setup.captureCharFrame();
        return {
            titleY: rowY(frame, "Models"),
            rows: frame
                .split("\n")
                .filter((line) => /model-[0-9a-c]/.test(line)).length,
        };
    };

    const short = await render(GROUPED);
    const long = await render(ITEMS);
    // 3 items + 2 headers + 1 spacer: the panel is shorter, so it starts lower
    expect(short.rows).toBe(3);
    expect(short.titleY).toBeGreaterThan(long.titleY);
    expect(long.rows).toBe(12);
});


test("group headers use the accent text colour, items the body colour", async () => {
    const setup = await testRender(
        <SearchableList
            title="Models"
            items={GROUPED}
            onSelect={() => {}}
            onClose={() => {}}
        />,
        { width: WIDTH, height: HEIGHT },
    );
    await setup.flush();
    const spans = setup.captureSpans();
    const frame = setup.captureCharFrame();
    const header = spanAt(spans, rowY(frame, "OpenAI"), "OpenAI")!;
    const item = spanAt(spans, rowY(frame, "model-b"), "model-b")!;
    expect(Array.from(header.fg.buffer).slice(0, 3)).toEqual(
        rgbOf(darkTheme.accentText),
    );
    expect(Array.from(item.fg.buffer).slice(0, 3)).toEqual(
        rgbOf(darkTheme.foreground),
    );
    expect(Array.from(header.fg.buffer)).not.toEqual(
        Array.from(item.fg.buffer),
    );
});

test("pressing Enter once submits once", async () => {
    let picks = 0;
    const setup = await testRender(
        <SearchableList
            title="Models"
            items={GROUPED}
            onSelect={() => {
                picks += 1;
            }}
            onClose={() => {}}
        />,
        { width: WIDTH, height: HEIGHT },
    );
    await setup.flush();
    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("\r"));
    });
    await setup.flush();
    expect(picks).toBe(1);
});




test("pressing up at the first row scrolls the group header back into view", async () => {
    const items = [
        ...Array.from({ length: 10 }, (_, i) => ({
            label: `a-${i}`,
            value: `a${i}`,
            group: "Alpha",
        })),
        ...Array.from({ length: 10 }, (_, i) => ({
            label: `b-${i}`,
            value: `b${i}`,
            group: "Beta",
        })),
    ];
    const setup = await testRender(
        <SearchableList
            title="Models"
            items={items}
            onSelect={() => {}}
            onClose={() => {}}
        />,
        { width: WIDTH, height: HEIGHT },
    );
    await setup.flush();
    const frame = () => setup.captureCharFrame();
    expect(frame()).toContain("Alpha");

    const y = rowY(frame(), "a-3");
    await act(async () => {
        await setup.mockMouse.scroll(20, y, "down");
    });
    await setup.flush();
    expect(frame()).not.toContain("Alpha");

    for (let press = 0; press < 10; press += 1) {
        await act(async () => {
            setup.renderer.stdin.emit("data", Buffer.from("\x1b[A"));
        });
        await setup.flush();
    }
    expect(frame()).toContain("Alpha");
    expect(frame()).toContain("1/20");
});
