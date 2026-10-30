import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import {
    loadCatalog,
    loadModels,
    modelLabel,
    providerLabel,
    resetCatalog,
} from "./catalog.ts";

const originalFetch = globalThis.fetch;
let calls = 0;

beforeEach(() => {
    resetCatalog();
    calls = 0;
    globalThis.fetch = ((input: RequestInfo | URL) => {
        calls += 1;
        const url = String(input);
        if (url.endsWith("/api/models")) {
            return Promise.resolve(
                Response.json({
                    items: [
                        {
                            id: "m1",
                            provider: "p1",
                            provider_name: "P1",
                            model: "beam-free",
                            label: "Beam Free",
                            tools: true,
                        },
                    ],
                }),
            );
        }
        return Promise.resolve(
            Response.json({ items: [{ key: "p1", name: "Provider One" }] }),
        );
    }) as typeof fetch;
});

afterEach(() => {
    globalThis.fetch = originalFetch;
    resetCatalog();
});

describe("catalog", () => {
    test("fetches models and providers once", async () => {
        const first = await loadCatalog();
        const second = await loadCatalog();
        expect(second).toBe(first);
        expect(calls).toBe(2);
        expect(first.models).toHaveLength(1);
        expect(first.providers).toHaveLength(1);
    });

    test("the model list is fetched once per process", async () => {
        const first = await loadModels();
        const second = await loadModels();

        expect(second).toBe(first);
        // Opening a screen must not cost a request.
        expect(calls).toBe(1);
    });

    test("a screen and the catalog share the model request", async () => {
        const models = await loadModels();
        const catalog = await loadCatalog();

        expect(catalog.models).toBe(models);
        // One request for models, one for providers -- shared, not repeated.
        expect(calls).toBe(2);
    });

    test("resolves model and provider labels", async () => {
        const catalog = await loadCatalog();
        expect(modelLabel(catalog, "p1", "beam-free")).toBe("Beam Free");
        expect(providerLabel(catalog, "p1")).toBe("Provider One");
    });

    test("falls back to the keys when unknown", async () => {
        const catalog = await loadCatalog();
        expect(modelLabel(catalog, "p1", "missing")).toBe("missing");
        expect(providerLabel(catalog, "missing")).toBe("missing");
        expect(modelLabel(null, "p1", "beam-free")).toBe("beam-free");
        expect(providerLabel(null, "p1")).toBe("p1");
    });
});
