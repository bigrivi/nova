import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";

const CONNECTION_KEY = "nova.mobile.connection.v1";
const TABS_KEY = "nova.mobile.tabs.v1";
const EXPANDED_PROJECTS_KEY = "nova.mobile.expanded-projects.v1";

export type StoredConnection = {
    baseUrl: string;
    username: string;
    password: string;
};

export async function loadConnection(): Promise<StoredConnection | null> {
    try {
        const raw = await SecureStore.getItemAsync(CONNECTION_KEY);
        if (raw) {
            return JSON.parse(raw) as StoredConnection;
        }
    } catch {
        // SecureStore is unavailable on web and can fail on a locked keychain.
    }
    try {
        const raw = await AsyncStorage.getItem(CONNECTION_KEY);
        if (raw) {
            return JSON.parse(raw) as StoredConnection;
        }
    } catch {
        // A failed read is the same as nothing stored.
    }
    return null;
}

export async function saveConnection(
    connection: StoredConnection,
): Promise<void> {
    const raw = JSON.stringify(connection);
    try {
        await SecureStore.setItemAsync(CONNECTION_KEY, raw);
        await AsyncStorage.removeItem(CONNECTION_KEY);
        return;
    } catch {
        // Fall through to unencrypted storage; the UI says the phone is not
        // protecting the credential, and the value is still local.
    }
    await AsyncStorage.setItem(CONNECTION_KEY, raw);
}

export async function clearConnection(): Promise<void> {
    try {
        await SecureStore.deleteItemAsync(CONNECTION_KEY);
    } catch {
        // Nothing to delete.
    }
    await AsyncStorage.removeItem(CONNECTION_KEY);
}

export async function readTabsFile(): Promise<unknown> {
    try {
        const raw = await AsyncStorage.getItem(TABS_KEY);
        return raw ? (JSON.parse(raw) as unknown) : null;
    } catch {
        return null;
    }
}

export async function writeTabsFile(value: unknown): Promise<void> {
    try {
        await AsyncStorage.setItem(TABS_KEY, JSON.stringify(value));
    } catch {
        // A failed write must not break the UI.
    }
}

export async function clearTabsFile(): Promise<void> {
    await AsyncStorage.removeItem(TABS_KEY);
}

export async function readExpandedProjects(): Promise<string[]> {
    try {
        const raw = await AsyncStorage.getItem(EXPANDED_PROJECTS_KEY);
        if (!raw) {
            return [];
        }
        const parsed = JSON.parse(raw) as unknown;
        return Array.isArray(parsed)
            ? parsed.filter((item): item is string => typeof item === "string")
            : [];
    } catch {
        return [];
    }
}

export async function writeExpandedProjects(ids: string[]): Promise<void> {
    try {
        await AsyncStorage.setItem(
            EXPANDED_PROJECTS_KEY,
            JSON.stringify(ids),
        );
    } catch {
        // Losing the open/closed preference is harmless.
    }
}
