import { useEffect, useRef, useState } from "react";

import type { GroupMember, GroupSettings } from "../types";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  /** Group rooms only: the slot of the companion who said it. */
  speaker?: string | null;
}

export interface DebugEntry {
  category: string;
  label: string;
  data: unknown;
  at: string;
}

/** Application close code meaning "your session is gone". The server accepts
 *  the socket and then closes with this, because a refused handshake reaches
 *  the browser with no readable code. */
export const WS_UNAUTHENTICATED = 4401;

/** Group room close codes that retrying cannot fix: the feature is off, or her
 *  own companion does not exist yet. */
const WS_TERMINAL = new Set([4404, 4409]);

export interface ChatSocketOptions {
  /** `/ws` for the 1:1 chat, `/ws/group` for the shared room. */
  path?: string;
  /** Group protocol: several speakers per turn, so only `turn_end` ends it. */
  group?: boolean;
}

/** WebSocket client for the /ws protocol:
 *  message | history_end | message_start | message_chunk | message_end | debug,
 *  plus, on /ws/group: members | settings | turn_start | turn_end, and a
 *  `speaker` on every assistant event.
 *
 *  @param onUnauthenticated called when the server reports the session is gone.
 */
export function useChatSocket(
  onUnauthenticated?: () => void,
  { path = "/ws", group = false }: ChatSocketOptions = {},
) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [members, setMembers] = useState<GroupMember[]>([]);
  // Group rooms: the server's word on the room's controls (null until it speaks).
  const [roomSettings, setRoomSettings] = useState<GroupSettings | null>(null);
  const [debug, setDebug] = useState<DebugEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  // Set when the server refuses a turn on the free plan's daily allowance.
  const [quotaExceeded, setQuotaExceeded] = useState(false);
  // Set when the server closed for good (group room unavailable).
  const [unavailable, setUnavailable] = useState(false);
  const socket = useRef<WebSocket | null>(null);
  const streaming = useRef(false);
  // Held in a ref so a new callback identity doesn't tear down the socket.
  const onUnauthenticatedRef = useRef(onUnauthenticated);
  onUnauthenticatedRef.current = onUnauthenticated;

  useEffect(() => {
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;

    function connect() {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${proto}//${window.location.host}${path}`);
      socket.current = ws;
      setMessages([]);
      streaming.current = false;

      ws.onopen = () => setConnected(true);

      ws.onclose = (event) => {
        setConnected(false);
        setBusy(false);
        // Without this the 2s retry becomes an infinite reconnect loop against
        // a server that will keep rejecting us. Any other close code is a
        // transient drop (restart, network) and should still retry.
        if (event.code === WS_UNAUTHENTICATED) {
          closed = true;
          onUnauthenticatedRef.current?.();
          return;
        }
        if (WS_TERMINAL.has(event.code)) {
          closed = true;
          setUnavailable(true);
          return;
        }
        if (!closed) retry = setTimeout(connect, 2000);
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        switch (data.type) {
          case "members":
            setMembers(data.members);
            break;
          case "settings":
            setRoomSettings({ response_length: data.response_length, talk_mode: data.talk_mode });
            break;
          case "message":
            setMessages((prev) => [
              ...prev,
              { role: data.role, content: data.content, speaker: data.speaker ?? null },
            ]);
            break;
          case "turn_start":
            setBusy(true);
            break;
          case "message_start":
            streaming.current = true;
            setMessages((prev) => [
              ...prev,
              { role: "assistant", content: "", speaker: data.speaker ?? null },
            ]);
            break;
          case "message_chunk":
            setMessages((prev) => {
              if (!streaming.current) {
                streaming.current = true;
                return [
                  ...prev,
                  { role: "assistant", content: data.content, speaker: data.speaker ?? null },
                ];
              }
              const next = [...prev];
              const last = next[next.length - 1];
              next[next.length - 1] = { ...last, content: last.content + data.content };
              return next;
            });
            break;
          case "message_end":
            streaming.current = false;
            // In a room the next companion may still be about to speak.
            if (!group) setBusy(false);
            break;
          case "turn_end":
            streaming.current = false;
            setBusy(false);
            break;
          case "quota_exceeded":
            // The server already declined the turn; this only explains why.
            setBusy(false);
            setQuotaExceeded(true);
            break;
          case "debug":
            setDebug((prev) => [
              ...prev.slice(-199),
              {
                category: data.category,
                label: data.label,
                data: data.data,
                at: new Date().toLocaleTimeString(),
              },
            ]);
            break;
          default:
            break;
        }
      };
    }

    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      socket.current?.close();
    };
  }, [path, group]);

  /** `extra` rides along with the text — the group room's `target`. */
  function send(content: string, extra: Record<string, unknown> = {}) {
    const text = content.trim();
    const ws = socket.current;
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ content: text, ...extra }));
    setBusy(true);
  }

  /** Group rooms: change the room's controls. Not a message — nothing to wait for. */
  function sendSettings(patch: Partial<GroupSettings>) {
    const ws = socket.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: "settings", ...patch }));
  }

  return {
    messages,
    members,
    roomSettings,
    debug,
    connected,
    busy,
    quotaExceeded,
    unavailable,
    send,
    sendSettings,
  };
}
