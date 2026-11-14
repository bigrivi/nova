/** The bottom of the app: a question card, an approval dialog, or the composer.
 *
 *  The composer lives in one wrapper box for both layouts, so switching
 *  between the launch card and the plain bar only changes props: the draft
 *  inside the composer survives the switch.
 */
import { useTheme } from "../context/theme.tsx";
import { useApprovalStore } from "../stores/approval-store.ts";
import { useAskUserStore } from "../stores/ask-user-store.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { submitAskAnswers, submitAskCancel } from "../stream/chat-stream.ts";
import { ApprovalDialog } from "./ApprovalDialog.tsx";
import { AskUserCard } from "./AskUserCard.tsx";
import { Composer, type ComposerCommandHandler } from "./Composer.tsx";
import { LaunchFrame } from "./screens/LaunchFrame.tsx";
import { LaunchScreen } from "./screens/LaunchScreen.tsx";
import { hintAt } from "./screens/launch.ts";

type BottomDockProps = {
    launching: boolean;
    hintIndex: number;
    hints: string[];
    animate: boolean;
    onCommand: ComposerCommandHandler;
};

function NoModelNotice() {
    const theme = useTheme();
    return (
        <box marginTop={1}>
            <text
                fg={theme.feedback.running}
                content="No model selected — type /models"
            />
        </box>
    );
}

export function BottomDock({
    launching,
    hintIndex,
    hints,
    animate,
    onCommand,
}: BottomDockProps) {
    const askQuestions = useAskUserStore((state) => state.active);
    const approval = useApprovalStore((state) => state.pending);
    const needsModel = useChatStore((state) => !state.provider || !state.model);

    if (askQuestions) {
        return (
            <AskUserCard
                questions={askQuestions}
                onSubmit={(answers) => {
                    void submitAskAnswers(askQuestions, answers);
                }}
                onCancel={() => submitAskCancel(askQuestions)}
            />
        );
    }
    if (approval) {
        return <ApprovalDialog pending={approval} />;
    }
    return (
        <box
            flexDirection="column"
            flexGrow={launching ? 1 : 0}
            flexShrink={0}
            justifyContent={launching ? "center" : "flex-start"}
            alignItems={launching ? "center" : "stretch"}
        >
            {launching ? <LaunchScreen /> : null}
            <LaunchFrame active={launching}>
                <Composer
                    onCommand={onCommand}
                    variant={launching ? "card" : "bar"}
                    placeholder={
                        launching
                            ? animate
                                ? hintAt(hintIndex, hints)
                                : hints[0]
                            : undefined
                    }
                />
            </LaunchFrame>
            {launching && needsModel ? <NoModelNotice /> : null}
        </box>
    );
}
