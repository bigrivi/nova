import { expect, test } from "bun:test";
import { buildUrl, setApiBase } from "./client.ts";

test("a learned address is where every later request goes", () => {
    // The backend is asked for a free port, so the address is only known at
    // runtime; a module-level constant would keep every request pointed at the
    // configured port while the server listened somewhere else.
    const before = buildUrl("");

    try {
        setApiBase("http://127.0.0.1:51914/");

        expect(buildUrl("/health")).toBe("http://127.0.0.1:51914/health");
    } finally {
        setApiBase(before);
    }
});
