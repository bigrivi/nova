/** Model/provider display names, fetched once per TUI process.
 *
 * Rendering needs friendly labels for the provider/model keys stored in the chat
 * store. The catalog is immutable for the process lifetime, so a single fetch is
 * cached behind this module instead of being re-requested whenever the user
 * switches models.
 */
import { listModels, listProviders } from "../api/nova-api.ts";
import type { NovaModelRecord, NovaProviderRecord } from "../api/types.ts";

export type Catalog = {
    models: NovaModelRecord[];
    providers: NovaProviderRecord[];
};

let catalogPromise: Promise<Catalog> | null = null;
let modelsPromise: Promise<NovaModelRecord[]> | null = null;

/**
 * The model list, fetched once per process.
 *
 * Screens that need models (the picker, the effort picker) share this rather
 * than calling the endpoint themselves: opening a screen must not cost a
 * request, and the file it reflects is read at startup anyway. A changed
 * `config.json` is picked up by restarting the TUI, not by refetching per open.
 */
export function loadModels(): Promise<NovaModelRecord[]> {
    modelsPromise ??= listModels();
    return modelsPromise;
}

/** Load the catalog, reusing the first in-flight or settled request. */
export function loadCatalog(): Promise<Catalog> {
    catalogPromise ??= Promise.all([loadModels(), listProviders()]).then(
        ([models, providers]) => ({ models, providers }),
    );
    return catalogPromise;
}

/** Drop the cache. Only tests should need this. */
export function resetCatalog(): void {
    catalogPromise = null;
    modelsPromise = null;
}

/** The model's display label, falling back to its key. */
export function modelLabel(
    catalog: Catalog | null,
    provider: string,
    model: string,
): string {
    return (
        catalog?.models.find(
            (item) => item.provider === provider && item.model === model,
        )?.label ?? model
    );
}

/** The provider's display name, falling back to its key. */
export function providerLabel(
    catalog: Catalog | null,
    provider: string,
): string {
    return catalog?.providers.find((item) => item.key === provider)?.name ?? provider;
}
