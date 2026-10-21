import type { ChatMessage } from "./useChatSocket";

/** Whether to show the typing indicator instead of a bubble.
 *
 *  The socket sends `message_start` before the first chunk, which appends an
 *  empty assistant message — so "she is thinking" covers both the gap after the
 *  user's turn and that placeholder, and ends the moment real text arrives.
 */
export function isAwaitingReply(messages: ChatMessage[], busy: boolean): boolean {
  if (!busy) return false;
  const last = messages[messages.length - 1];
  if (!last) return true;
  return last.role === "user" || last.content === "";
}

/** An assistant message with no text yet is the streaming placeholder; the
 *  indicator stands in for it, so rendering both would show an empty bubble. */
export function isPlaceholder(message: ChatMessage): boolean {
  return message.role === "assistant" && message.content === "";
}

/** Who the typing indicator stands for in a group room: the speaker of the
 *  streaming placeholder, or null while nobody has started yet. */
export function typingSpeaker(messages: ChatMessage[]): string | null {
  const last = messages[messages.length - 1];
  if (!last || !isPlaceholder(last)) return null;
  return last.speaker ?? null;
}
