/** Session panel geometry: how wide it is, and how wide the terminal must be
 *  for it to sit beside the transcript instead of covering it. */
export const SIDEBAR_WIDTH = 34;
/** The transcript keeps this much room when the panel is docked. */
export const SIDEBAR_CONTENT_WIDTH = 72;
/** Below this the panel takes the screen: a 40-column transcript is not a
 *  transcript, it is a column of broken code blocks. */
export const SIDEBAR_DOCK_MIN_WIDTH = SIDEBAR_WIDTH + SIDEBAR_CONTENT_WIDTH;
