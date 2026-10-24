/** Theme screen: browse/switch UI themes */
import { useThemePreference } from "../../context/theme.tsx";
import { useScreenStore } from "../../stores/screen-store.ts";
import { SearchableList } from "./SearchableList.tsx";

export function ThemeScreen() {
    const { preference, setPreference, available } = useThemePreference();

    return (
        <SearchableList
            title="Themes"
            items={available}
            filter={(item, query) =>
                !query || item.toLowerCase().includes(query.toLowerCase())
            }
            renderLabel={(item) =>
                item === preference ? `${item}  (current)` : item
            }
            onSelect={(item) => {
                setPreference(item);
                useScreenStore.getState().close();
            }}
            onClose={() => useScreenStore.getState().close()}
            emptyText="no themes available"
            initialIndex={Math.max(0, available.indexOf(preference))}
        />
    );
}
