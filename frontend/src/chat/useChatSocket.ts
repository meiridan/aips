import { useEffect, useRef, useState } from "react";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
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

/** WebSocket client for the existing /ws protocol:
 *  message | history_end | message_start | message_chunk | message_end | debug.
 *
 *  @param onUnauthenticated called when the server reports the session is gone.
 */
export function useChatSocket(onUnauthenticated?: () => void) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [debug, setDebug] = useState<DebugEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  // Set when the server refuses a turn on the free plan's daily allowance.
  const [quotaExceeded, setQuotaExceeded] = useState(false);
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
      const ws = new WebSocket(`${proto}//${window.location.host}/ws`);
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
        if (!closed) retry = setTimeout(connect, 2000);
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        switch (data.type) {
          case "message":
            setMessages((prev) => [...prev, { role: data.role, content: data.content }]);
            break;
          case "message_start":
            streaming.current = true;
            setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
            break;
          case "message_chunk":
            setMessages((prev) => {
              if (!streaming.current) {
                streaming.current = true;
                return [...prev, { role: "assistant", content: data.content }];
              }
              const next = [...prev];
              const last = next[next.length - 1];
              next[next.length - 1] = { ...last, content: last.content + data.content };
              return next;
            });
            break;
          case "message_end":
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
  }, []);

  function send(content: string) {
    const text = content.trim();
    const ws = socket.current;
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ content: text }));
    setBusy(true);
  }

  return { messages, debug, connected, busy, quotaExceeded, send };
}
