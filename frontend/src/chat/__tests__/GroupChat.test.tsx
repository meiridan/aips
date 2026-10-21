import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GroupChat from "../GroupChat";

class FakeSocket {
  static OPEN = 1;
  static instances: FakeSocket[] = [];
  readyState = 1;
  sent: unknown[] = [];
  onopen?: () => void;
  onclose?: (event: { code: number }) => void;
  onmessage?: (event: { data: string }) => void;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(JSON.parse(data));
  }

  close() {}

  emit(...events: object[]) {
    act(() => {
      for (const event of events) this.onmessage?.({ data: JSON.stringify(event) });
    });
  }
}

const strings: Record<string, string> = {
  group_error: "שגיאה",
  group_joining: "מצטרפת…",
  group_back: "חזרה",
  group_and: "ו",
  group_target: "למי:",
  group_target_all: "לשתיהן",
  group_typing_many: "מקלידות…",
  group_hint: "כתבו…",
  group_talk_free: "שיחה חופשית",
  group_talk_moderated: "שיחה מנוהלת",
  reply_length: "אורך תשובה",
  length_1: "קצר",
  length_2: "בינוני",
  length_3: "ארוך",
  chat_typing: "מקלידה…",
  chat_send: "שליחה",
  connected: "מחובר",
  disconnected: "מנותק",
};

const members = [
  { id: "1", slot: "primary", name: "מאיה", avatar_path: null },
  { id: "2", slot: "lila", name: "לילה", avatar_path: null },
];

async function openRoom() {
  render(<GroupChat strings={strings} onBack={() => {}} />);
  await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
  const ws = FakeSocket.instances[0];
  act(() => ws.onopen?.());
  ws.emit({ type: "members", members }, { type: "history_end" });
  return ws;
}

function type(text: string) {
  fireEvent.change(screen.getByPlaceholderText(strings.group_hint), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: strings.chat_send }));
}

beforeEach(() => {
  // jsdom has no layout, so no Element.scrollTo; the feed calls it on every update.
  Element.prototype.scrollTo = vi.fn();
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ conversation_id: "c", members }))),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("GroupChat", () => {
  it("joins the group socket and titles the room with both names", async () => {
    const ws = await openRoom();
    expect(ws.url.endsWith("/ws/group")).toBe(true);
    expect(screen.getByText("מאיה ולילה")).toBeTruthy();
  });

  it("labels and colours each companion's bubble by seat", async () => {
    const ws = await openRoom();
    ws.emit(
      { type: "turn_start", addressed: ["primary", "lila"] },
      { type: "message_start", speaker: "primary" },
      { type: "message_chunk", speaker: "primary", content: "בוקר טוב" },
      { type: "message_end", speaker: "primary" },
      { type: "message_start", speaker: "lila" },
      { type: "message_chunk", speaker: "lila", content: "גם ממני" },
    );
    expect(screen.getByText("בוקר טוב").closest(".bubble")?.className).toContain("seat-0");
    expect(screen.getByText("גם ממני").closest(".bubble")?.className).toContain("seat-1");
  });

  it("keeps the typing indicator between speakers until the turn ends", async () => {
    const ws = await openRoom();
    ws.emit(
      { type: "turn_start", addressed: ["primary", "lila"] },
      { type: "message_start", speaker: "primary" },
      { type: "message_chunk", speaker: "primary", content: "היי" },
      { type: "message_end", speaker: "primary" },
      { type: "message_start", speaker: "lila" },
    );
    expect(screen.getByRole("status").getAttribute("aria-label")).toBe("לילה מקלידה…");
    ws.emit({ type: "message_end", speaker: "lila" }, { type: "turn_end" });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("lets the text decide until a target chip is picked", async () => {
    const ws = await openRoom();
    type("שלום");
    expect(ws.sent.at(-1)).toEqual({ content: "שלום" });

    fireEvent.click(screen.getByRole("radio", { name: "לילה" }));
    type("רק לך");
    expect(ws.sent.at(-1)).toEqual({ content: "רק לך", target: "lila" });

    fireEvent.click(screen.getByRole("radio", { name: "לילה" }));
    type("שוב לשתיכן");
    expect(ws.sent.at(-1)).toEqual({ content: "שוב לשתיכן" });
  });

  it("changes reply length and talk mode over the socket", async () => {
    const ws = await openRoom();
    fireEvent.click(screen.getByRole("button", { name: "ארוך" }));
    expect(ws.sent.at(-1)).toEqual({ type: "settings", response_length: 3 });
    expect(screen.getByRole("button", { name: "ארוך" }).getAttribute("aria-pressed")).toBe("true");

    // The label is the mode the room is in; tapping it switches.
    fireEvent.click(screen.getByRole("button", { name: "שיחה מנוהלת" }));
    expect(ws.sent.at(-1)).toEqual({ type: "settings", talk_mode: "free" });
    fireEvent.click(screen.getByRole("button", { name: "שיחה חופשית" }));
    expect(ws.sent.at(-1)).toEqual({ type: "settings", talk_mode: "moderated" });
  });

  it("shows the settings the server reports", async () => {
    const ws = await openRoom();
    ws.emit({ type: "settings", response_length: 2, talk_mode: "free" });
    expect(screen.getByRole("button", { name: "שיחה חופשית" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "בינוני" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
  });
});
