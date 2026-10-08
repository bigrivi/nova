import { describe, expect, it } from "vitest";

import { approvalScope } from "./approval-scope";

const base = { rememberable: true, family: "curl * python3 *", scriptScoped: false };

describe("approvalScope", () => {
    it("names the script when the grant is narrowed to one", () => {
        // The whole point of the third key part: the button must not read as
        // "remember every python3 -c in this family" when it is not.
        expect(approvalScope({ ...base, scriptScoped: true })).toEqual({
            key: "approval.rememberScript",
        });
    });

    it("prefers the script over the family when both are present", () => {
        // A script-scoped grant always has a family too, because the family is
        // still part of the key. Naming the family would overstate the width, so
        // the narrower of the two is the one shown.
        expect(
            approvalScope({
                rememberable: true,
                family: "curl * python3 *",
                scriptScoped: true,
            }),
        ).toEqual({ key: "approval.rememberScript" });
    });

    it("names the family when there is no script", () => {
        expect(approvalScope(base)).toEqual({
            key: "approval.rememberFamily",
            family: "curl * python3 *",
        });
    });

    it("says nothing when the reviewer declined", () => {
        // The button is hidden in that case, so a scope line would be describing
        // a decision that will not be stored.
        expect(approvalScope({ ...base, rememberable: false })).toBeNull();
        expect(
            approvalScope({ ...base, rememberable: false, scriptScoped: true }),
        ).toBeNull();
    });

    it("says nothing when there is neither a script nor a family", () => {
        // An unreadable command line: the grant covers the whole rule. There is no
        // narrower label to give, and a wrong one would be worse than none.
        expect(approvalScope({ ...base, family: "" })).toBeNull();
        expect(approvalScope({ ...base, family: "", scriptScoped: false })).toBeNull();
    });

    it("still names the script when the family is missing", () => {
        // Independent: the two parts of the key are read separately, and a script
        // with no family is still a script worth naming.
        expect(approvalScope({ ...base, family: "", scriptScoped: true })).toEqual({
            key: "approval.rememberScript",
        });
    });
});
