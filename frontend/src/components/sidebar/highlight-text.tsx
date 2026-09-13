import { Fragment, type ReactNode } from "react";

export function HighlightedText({
    text,
    query,
}: {
    text: string;
    query: string;
}): ReactNode {
    const needle = query.trim();
    if (!needle) {
        return text;
    }
    const index = text.toLocaleLowerCase().indexOf(needle.toLocaleLowerCase());
    if (index < 0) {
        return text;
    }
    return (
        <Fragment>
            {text.slice(0, index)}
            <mark className="rounded-sm bg-[#FCEFC7] text-inherit">
                {text.slice(index, index + needle.length)}
            </mark>
            {text.slice(index + needle.length)}
        </Fragment>
    );
}
