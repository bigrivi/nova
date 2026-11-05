import { describe, expect, test } from "bun:test";

import {
    authHeader,
    configureClient,
    normalizeBaseUrl,
} from "./client";

describe("server URL", () => {
    test("adds http when the scheme is missing", () => {
        expect(normalizeBaseUrl("192.168.1.5:8765")).toBe(
            "http://192.168.1.5:8765",
        );
    });

    test("keeps https and strips trailing slashes", () => {
        expect(normalizeBaseUrl("https://nova.example/")).toBe(
            "https://nova.example",
        );
        expect(normalizeBaseUrl("https://nova.example/proxy/")).toBe(
            "https://nova.example/proxy",
        );
    });

    test("rejects a non-http scheme and an empty value", () => {
        expect(() => normalizeBaseUrl("ftp://host")).toThrow();
        expect(() => normalizeBaseUrl("   ")).toThrow();
    });
});

describe("basic auth", () => {
    test("encodes the credentials as a Basic header", () => {
        configureClient({
            baseUrl: "https://host",
            username: "alice",
            password: "secret",
        });
        expect(authHeader()).toEqual({
            Authorization: "Basic YWxpY2U6c2VjcmV0",
        });
    });

    test("sends no header without credentials", () => {
        configureClient({
            baseUrl: "https://host",
            username: "",
            password: "",
        });
        expect(authHeader()).toEqual({});
    });
});
