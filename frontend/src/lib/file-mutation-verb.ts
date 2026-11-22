/**
 * The verb the file-mutation card's title uses.
 *
 * Kept out of the component for the same reason `approval-scope.ts` was: the
 * decision has cases, the repo has no component-test setup, and a ternary
 * inside JSX is only ever checked by the type checker.
 *
 * The verb tracks how the call *ended*, not which tool it was. The card used to
 * read "Wrote <file>" the moment the model announced the call, so a write that
 * was still waiting for approval -- and one the user then rejected -- both
 * claimed a write that never happened. A call with no result yet is in progress
 * and says so; only a settled, non-error call gets the past tense.
 */

export type MutationVerbKey =
    | "tools.edited"
    | "tools.wrote"
    | "tools.editing"
    | "tools.writing"
    | "tools.preparingWrite";

export type MutationVerbInput = {
    /** Whether the call has a result at all; false while it is still running. */
    hasResult: boolean;
    /** Whether the settled result was flagged as an error (a rejection is one). */
    isError: boolean;
    /**
     * Whether any arguments have arrived. A call announced by
     * `tool-input-start` has none yet: the model is still composing the payload.
     */
    hasInput: boolean;
};

/**
 * The i18n key for the card's verb.
 *
 * @param toolName - The tool the call names; `edit` is distinguished from
 *     `write`, every other value reads as a write.
 * @param input - Whether the call has settled, how it settled, and whether its
 *     arguments have arrived.
 * @returns "Preparing write" until arguments arrive, the past tense once the
 *     call succeeded, the progressive form otherwise.
 */
export function mutationVerbKey(
    toolName: string,
    input: MutationVerbInput,
): MutationVerbKey {
    const isEdit = toolName.trim().toLowerCase() === "edit";
    const finished = input.hasResult && !input.isError;
    if (isEdit) {
        return finished ? "tools.edited" : "tools.editing";
    }
    if (!input.hasResult && !input.hasInput) {
        return "tools.preparingWrite";
    }
    return finished ? "tools.wrote" : "tools.writing";
}
