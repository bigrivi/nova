/** Theme screen: browse/switch UI themes */
import { useThemePreference } from "../../context/theme.tsx";
import { useScreenStore } from "../../stores/screen-store.ts";
import { SearchableList } from "./SearchableList.tsx";

export function ThemeScreen() {
    const { preference, setPreference, available } = useThemePreference();

    return (
        <SearchableList
            title="Themes"
            items={available.map((name) => ({ label: name, value: name }))}
            defaultValue={preference}
            onSelect={(value) => {
                setPreference(value);
                useScreenStore.getState().close();
            }}
            onClose={() => useScreenStore.getState().close()}
            emptyText="no themes available"
        />
    );
}
