/** Process-wide catalog context: fetched once, shared by every consumer. */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { loadCatalog, type Catalog } from "../lib/catalog.ts";

const CatalogContext = createContext<Catalog | null>(null);

export function CatalogProvider({ children }: { children: ReactNode }) {
    const [catalog, setCatalog] = useState<Catalog | null>(null);

    useEffect(() => {
        let cancelled = false;
        void loadCatalog()
            .then((next) => {
                if (!cancelled) setCatalog(next);
            })
            .catch(() => {});
        return () => {
            cancelled = true;
        };
    }, []);

    return (
        <CatalogContext.Provider value={catalog}>
            {children}
        </CatalogContext.Provider>
    );
}

/** The shared catalog, or null until the first fetch resolves. */
export function useCatalog(): Catalog | null {
    return useContext(CatalogContext);
}
