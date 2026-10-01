/**
 * In-chat approval for dangerous commands.
 *
 * Nova blocks a turn on `approval.required` and holds it open, heartbeating
 * until `POST /api/chat/approve` resolves the request. Over WeChat the user has
 * no dialog to click, so the bridge asks in chat and waits for a typed answer.
 *
 * The wait has no timeout of its own: Nova owns the deadline, and answering
 * after Nova gave up yields a 404 that the user sees as "expired".
 */

import * as log from "./log.js";

/** A pending dangerous-command approval awaiting a chat answer. */
interface PendingApproval {
  readonly requestId: string;
  readonly sessionId: string;
  readonly command: string;
  readonly description: string;
}

/** Classifies a chat message as an approval answer, or null if it is not one. */
export function parseApprovalReply(
  text: string,
): { approved: boolean; remember: boolean } | null {
  const normalized = text.trim().toLowerCase().replace(/^[!！。.\s]+/, "");
  if (!normalized) {
    return null;
  }
  if (/^(y|yes|ok|好|可以|同意|确认|批准)$/.test(normalized)) {
    return { approved: true, remember: false };
  }
  if (/^(a|all|总是|始终|以后都|永远)$/.test(normalized)) {
    return { approved: true, remember: true };
  }
  if (/^(n|no|否|不|不行|拒绝|取消)$/.test(normalized)) {
    return { approved: false, remember: false };
  }
  return null;
}

/**
 * One outstanding approval per conversation.
 *
 * A conversation is single-flight, so it can only ever be blocking on one
 * command at a time; a second request replaces the first, which is the honest
 * outcome since the first can no longer be answered.
 */
export class ApprovalRegistry {
  private readonly pending = new Map<string, PendingApproval>();

  /** Record a request and describe it for the chat. */
  open(conversationId: string, approval: PendingApproval): void {
    this.pending.set(conversationId, approval);
    log.info(
      `approval requested conv=${conversationId} req=${approval.requestId}`,
    );
  }

  /** Take the pending request for `conversationId`, if any. */
  take(conversationId: string): PendingApproval | undefined {
    const approval = this.pending.get(conversationId);
    if (approval !== undefined) {
      this.pending.delete(conversationId);
      log.info(`approval consumed conv=${conversationId} req=${approval.requestId}`);
    }
    return approval;
  }

  /** Forget a pending request without answering it, e.g. on `/stop`. */
  clear(conversationId: string): void {
    this.pending.delete(conversationId);
  }

  /** Whether `conversationId` is currently blocking on an approval. */
  has(conversationId: string): boolean {
    return this.pending.has(conversationId);
  }

  /** Render the confirmation prompt for a pending request. */
  static describe(approval: PendingApproval): string {
    const what = approval.description || "危险命令";
    return [
      `需要确认：${what}`,
      "",
      "```",
      approval.command,
      "```",
      "",
      "回复 y 允许 · n 拒绝 · a 始终允许本会话内同类命令",
    ].join("\n");
  }
}