import { useEffect, useRef, useState } from "react";

import { setResponseLength } from "../api";
import { ROUTES, navigate } from "../router";
import type { CompanionState } from "../types";
import TypingIndicator from "./TypingIndicator";
import { isAwaitingReply, isPlaceholder } from "./typing";
import { useChatSocket } from "./useChatSocket";

interface Props {
  companion: CompanionState;
  strings: Record<string, string>;
  /** Omitted in single-user mode: nothing to log out of, so no button. */
  onLogout?: () => void;
  /** Omitted when the server has group chat switched off. */
  onOpenGroup?: () => void;
}

export default function Chat({ companion, strings, onLogout, onOpenGroup }: Props) {
  // A dead session closes the socket with 4401; dropping to the login screen
  // is exactly what logout already does. Unreachable in single-user mode.
  const { messages, debug, connected, busy, quotaExceeded, send } = useChatSocket(onLogout);
  const [draft, setDraft] = useState("");
  const [level, setLevel] = useState(companion.response_length);
  const showDebug = new URLSearchParams(window.location.search).has("debug");
  const feed = useRef<HTMLDivElement>(null);

  // `busy` is in here too: the typing indicator appearing grows the feed just
  // like a message does, and it should not push itself out of sight.
  useEffect(() => {
    feed.current?.scrollTo({ top: feed.current.scrollHeight });
  }, [messages, busy]);

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
        {onOpenGroup && (
          <button type="button" className="header-link" onClick={onOpenGroup}>
            {strings.group_open}
          </button>
        )}
        <button
          type="button"
          className="header-link"
          onClick={() => navigate(ROUTES.subscription)}
        >
          {strings.to_subscription}
        </button>
        {onLogout && (
          <button type="button" className="header-link" onClick={onLogout}>
            {strings.logout}
          </button>
        )}
      </header>

      <div className="chat-messages" ref={feed}>
        {messages.map((message, i) =>
          isPlaceholder(message) ? null : (
            // Explicit rtl rather than "auto": a reply that opens with an
            // asterisked action, a quote or a Latin word resolves to LTR under
            // `auto` and lands left-aligned inside the bubble.
            <div key={i} className={`bubble ${message.role}`} dir="rtl">
              {message.content}
            </div>
          ),
        )}
        {isAwaitingReply(messages, busy) && (
          <TypingIndicator label={`${companion.name} ${strings.chat_typing}`} />
        )}
      </div>

      <form className="chat-input" onSubmit={submit}>
        {quotaExceeded && (
          <div className="quota-banner">
            <span>{strings.quota_exceeded}</span>
            <button type="button" onClick={() => navigate(ROUTES.subscription)}>
              {strings.quota_upgrade}
            </button>
          </div>
        )}
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
            // Explicit rtl, not "auto": an empty field has no first strong
            // character, so `auto` falls back to LTR and both the caret and the
            // Hebrew placeholder start on the wrong edge.
            dir="rtl"
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
