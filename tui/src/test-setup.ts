/**
 * Reset every store before each test.
 *
 * Test files share one module graph, so a store one file leaves dirty is still
 * dirty in the next one: an open mention menu or a stale draft changes the
 * frame a later file asserts on, and which file runs first is not the same on
 * every platform. Restoring the state each store had before any test ran is
 * what makes the suite order-independent.
 *
 * The test script runs one file at a time for that reason: a reset in one file
 * would otherwise wipe a store another file's test is still using, which reads
 * as a random failure in whichever test happened to be in flight.
 */
import { beforeEach } from "bun:test";

import * as approval from "./stores/approval-store.ts";
import * as askUser from "./stores/ask-user-store.ts";
import * as chat from "./stores/chat-store.ts";
import * as compaction from "./stores/compaction-store.ts";
import * as ctx from "./stores/ctx-store.ts";
import * as edit from "./stores/edit-store.ts";
import * as expand from "./stores/expand-store.ts";
import * as menu from "./stores/menu-store.ts";
import * as permission from "./stores/permission-store.ts";
import * as screen from "./stores/screen-store.ts";
import * as sidebar from "./stores/sidebar-store.ts";
import * as tab from "./stores/tab-store.ts";
import * as toast from "./stores/toast-store.ts";
import * as todo from "./stores/todo-store.ts";

type Resettable = {
    getState: () => unknown;
    setState: (state: unknown, replace?: boolean) => void;
};

function isStore(value: unknown): value is Resettable {
    const store = value as Partial<Resettable> | null;
    return (
        typeof store?.getState === "function" &&
        typeof store?.setState === "function"
    );
}

const modules = [
    approval,
    askUser,
    chat,
    compaction,
    ctx,
    edit,
    expand,
    menu,
    permission,
    screen,
    sidebar,
    tab,
    toast,
    todo,
];

const stores = modules.flatMap((module) =>
    Object.values(module).filter(isStore),
);
const initial = stores.map((store) => store.getState());

beforeEach(() => {
    stores.forEach((store, index) => store.setState(initial[index], true));
});
