/** Facade over the application context for the model/provider catalog. */
import { useApp } from "./app.tsx";
import type { Catalog } from "../lib/catalog.ts";

export function useCatalog(): Catalog | null {
    return useApp().catalog;
}
