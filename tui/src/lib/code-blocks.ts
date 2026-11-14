/** Extract fenced code blocks from a message's text. */

const CODE_BLOCK = /```(?:[^\n]*)\n([\s\S]*?)```/g;

/**
 * The code inside every fenced block in *text*, in order.
 *
 * A block with no language tag is still a block; the language tag is part
 * of the fence and never part of what gets copied.
 *
 * Args:
 *   text: The message body, possibly with several fenced blocks.
 *
 * Returns:
 *   One entry per block, the trailing newline trimmed so the copy does not
 *   add a blank line the user did not see.
 */
export function extractCodeBlocks(text: string): string[] {
    const blocks: string[] = [];
    CODE_BLOCK.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = CODE_BLOCK.exec(text)) !== null) {
        blocks.push((match[1] ?? "").replace(/\n$/, ""));
    }
    return blocks;
}
