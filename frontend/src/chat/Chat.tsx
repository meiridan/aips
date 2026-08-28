import { useEffect, useRef, useState } from "react";

import { setResponseLength } from "../api";
import type { CompanionState } from "../types";
import { useChatSocket } from "./useChatSocket";

interface Props {
  companion: CompanionState;
  strings: Record<string, string>;
}

export default function Chat({ companion, strings }: Props) {
  const { messages, debug, connected, busy, send } = useChatSocket();
  const [draft, setDraft] = useState("");
  const [level, setLevel] = useState(companion.response_length);
  const showDebug = new URLSearchParams(window.location.search).has("debug");
  const feed = useRef<HTMLDivElement>(null);

  useEffect(() => {
    feed.current?.scrollTo({ top: feed.current.scrollHeight });
  }, [messages]);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    send(draft);
    setDraft("");
  }

  function pickLevel(next: number) {
    setLevel(next);
    setResponseLength(next).catch(() => setLevel(level));
  }

  return (
    <div className="chat">
      <header className="chat-header">
        {companion.avatar_path ? (
          <img src={companion.avatar_path} alt="" />
        ) : (
          <div className="avatar-placeholder">💗</div>
        )}
        <div className="who">
          <div className="name">{companion.name}</div>
          <div className={`state ${connected ? "online" : ""}`}>
            {connected ? strings.connected : strings.disconnected}
          </div>
        </div>
      </header>

      <div className="chat-messages" ref={feed}>
        {messages.map((message, i) => (
          <div key={i} className={`bubble ${message.role}`} dir="auto">
            {message.content}
          </div>
        ))}
      </div>

      <form className="chat-input" onSubmit={submit}>
        <div className="length-row">
          <span>{strings.reply_length}</span>
          {[1, 2, 3].map((n) => (
            <button
              type="button"
              key={n}
              className={level === n ? "active" : ""}
              onClick={() => pickLevel(n)}
            >
              {strings[`length_${n}`]}
            </button>
          ))}
        </div>
        <div className="compose">
          <input
            value={draft}
            dir="auto"
            placeholder={strings.chat_placeholder}
            onChange={(e) => setDraft(e.target.value)}
          />
          <button type="submit" disabled={!connected || busy || !draft.trim()}>
            {strings.chat_send}
          </button>
        </div>
      </form>

      {showDebug && (
        <div className="debug">
          {debug.map((entry, i) => (
            <div key={i} className={`entry ${entry.category}`}>
              <div>
                {entry.at} · {entry.label}
              </div>
              {entry.data != null && Object.keys(entry.data).length > 0 && (
                <pre>{JSON.stringify(entry.data, null, 2)}</pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
