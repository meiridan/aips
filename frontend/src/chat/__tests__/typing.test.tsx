import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import TypingIndicator from "../TypingIndicator";
import { isAwaitingReply, isPlaceholder } from "../typing";
import type { ChatMessage } from "../useChatSocket";

const user = (content: string): ChatMessage => ({ role: "user", content });
const maya = (content: string): ChatMessage => ({ role: "assistant", content });

afterEach(cleanup);

describe("isAwaitingReply", () => {
  it("stays hidden while nothing is in flight", () => {
    expect(isAwaitingReply([user("היי")], false)).toBe(false);
    expect(isAwaitingReply([], false)).toBe(false);
  });

  it("shows after the user's turn is sent", () => {
    expect(isAwaitingReply([user("היי")], true)).toBe(true);
  });

  it("shows for the empty placeholder message_start appends", () => {
    expect(isAwaitingReply([user("היי"), maya("")], true)).toBe(true);
  });

  it("gives way to the real reply as soon as a chunk lands", () => {
    expect(isAwaitingReply([user("היי"), maya("אה")], true)).toBe(false);
  });

  it("shows on an empty feed while connecting a first turn", () => {
    expect(isAwaitingReply([], true)).toBe(true);
  });
});

describe("isPlaceholder", () => {
  it("is only the empty assistant message", () => {
    expect(isPlaceholder(maya(""))).toBe(true);
    expect(isPlaceholder(maya("שלום"))).toBe(false);
    // An empty user message is never rendered anyway, but it is not a placeholder.
    expect(isPlaceholder(user(""))).toBe(false);
  });
});

describe("TypingIndicator", () => {
  it("announces itself as a status with three dots", () => {
    const { container } = render(<TypingIndicator label="מאיה מקלידה…" />);
    const status = screen.getByRole("status");
    expect(status.getAttribute("aria-label")).toBe("מאיה מקלידה…");
    // Right-hand side with the user's turns: .bubble.typing, not .assistant.
    expect(status.className).toBe("bubble typing");
    expect(container.querySelectorAll(".typing-dot")).toHaveLength(3);
  });
});
