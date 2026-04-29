"use client";

import { useState, type FC } from "react";
import {
  MessagePartPrimitive,
  type ReasoningGroupProps,
} from "@assistant-ui/react";
import { BrainIcon, ChevronDownIcon } from "lucide-react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

export const Reasoning: FC = () => {
  return (
    <MessagePartPrimitive.Text
      component="div"
      className="whitespace-pre-wrap px-4 text-sm leading-6 text-muted-foreground"
    />
  );
};

export const ReasoningGroup: FC<ReasoningGroupProps> = ({
  children,
  startIndex,
  endIndex,
}) => {
  const [open, setOpen] = useState(false);
  const itemCount = endIndex - startIndex + 1;

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="rounded-2xl border bg-muted/40"
    >
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
        >
          <span className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <BrainIcon className="size-4" />
            {itemCount > 1 ? `Reasoning · ${itemCount} steps` : "Reasoning"}
          </span>
          <ChevronDownIcon
            className={cn(
              "size-4 text-muted-foreground transition-transform duration-200",
              open && "rotate-180",
            )}
          />
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
        <div className="space-y-3 border-t px-4 py-3">{children}</div>
      </CollapsibleContent>
    </Collapsible>
  );
};
