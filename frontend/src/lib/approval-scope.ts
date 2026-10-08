/**
 * What the "Approve & Remember" button will actually cover.
 *
 * The server keys a remembered approval on the rule, the command family, and --
 * when the command has a readable inline script -- the script itself. The dialog
 * has to say which, because a button that promises to remember something of
 * unknown width is asking the user to authorise more than they can see.
 *
 * The script case names the script rather than printing its digest. The digest is
 * a hash, and a hash is not something a person can act on; the script it stands
 * for is the command rendered directly above the buttons. So the honest label is
 * "this script", pointing at text that is already on screen.
 *
 * Extracted from the component for the same reason `tool-outcome.ts` was: this is
 * a decision with cases, the repo has no component-test setup, and a ternary
 * inside JSX is only ever checked by the type checker.
 */

/** The i18n key to render, or null when there is nothing to say. */
export type ApprovalScope =
    | { key: "approval.rememberScript" }
    | { key: "approval.rememberFamily"; family: string }
    | null;

export type ScopeInput = {
    /** False when a reviewer declined, which also hides the button. */
    rememberable: boolean;
    /** The command family the grant covers, e.g. `git push *`. */
    family: string;
    /** Whether the grant is narrowed to the inline script. */
    scriptScoped: boolean;
};

/**
 * The scope line to show under the command, or null to show none.
 *
 * Precedence is deliberate: a script-scoped grant is narrower than a
 * family-scoped one, so it is named first even when a family is also present --
 * which it always is, since the family is still part of the key. Naming the
 * family in that case would overstate what is being remembered.
 *
 * Nothing is returned when remembering is not on offer, or when there is no
 * family and no script to name. That is an unreadable command line, where the
 * grant covers the whole rule; the button is still honest there because the rule
 * is what the dialog is already about, and inventing a label would not be.
 */
export function approvalScope(input: ScopeInput): ApprovalScope {
    if (!input.rememberable) return null;
    if (input.scriptScoped) return { key: "approval.rememberScript" };
    if (input.family) return { key: "approval.rememberFamily", family: input.family };
    return null;
}
