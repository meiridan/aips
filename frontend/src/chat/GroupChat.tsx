import { useEffect, useRef, useState } from "react";

import { fetchGroup } from "../api";
import { ROUTES, navigate } from "../router";
import type { GroupMember, GroupSettings } from "../types";
import TypingIndicator from "./TypingIndicator";
import { isAwaitingReply, isPlaceholder, typingSpeaker } from "./typing";
import { useChatSocket } from "./useChatSocket";

interface Props {
  strings: Record<string, string>;
  onBack: () => void;
  /** Omitted in single-user mode: nothing to log out of, so no button. */
  onLogout?: () => void;
}

/** Target chip for "both of them" — explicit, unlike no chip at all. */
const TARGET_ALL = "all";

/** Until the server says otherwise — the same defaults as group_settings.py. */
const DEFAULT_SETTINGS: GroupSettings = { response_length: 1, talk_mode: "moderated" };

/** The shared room: the account's companion and her friend.
 *
 *  Opening it the first time brings the friend to life (a genesis call), so the
 *  room is fetched over HTTP before the socket connects — the socket then joins
 *  a room that already exists, and the wait gets a "joining" state instead of a
 *  silent reconnect loop.
 */
export default function GroupChat({ strings, onBack, onLogout }: Props) {
  const [members, setMembers] = useState<GroupMember[] | null>(null);
  const [settings, setSettings] = useState<GroupSettings>(DEFAULT_SETTINGS);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetchGroup()
      .then((room) => {
        setSettings(room.settings ?? DEFAULT_SETTINGS);
        setMembers(room.members);
      })
      .catch(() => setFailed(true));
  }, []);

  if (failed) {
    return (
      <div className="center-state">
        <p>{strings.group_error}</p>
        <button type="button" className="header-link" onClick={onBack}>
          {strings.group_back}
        </button>
      </div>
    );
  }

  if (!members) {
    return (
      <div className="center-state">
        <div className="spinner" />
        <p>{strings.group_joining}</p>
      </div>
    );
  }

  return (
    <Room
      initialMembers={members}
      initialSettings={settings}
      strings={strings}
      onBack={onBack}
      onLogout={onLogout}
    />
  );
}

interface RoomProps extends Props {
  initialMembers: GroupMember[];
  initialSettings: GroupSettings;
}

function Room({ initialMembers, initialSettings, strings, onBack, onLogout }: RoomProps) {
  const socket = useChatSocket(onLogout, { path: "/ws/group", group: true });
  const { messages, debug, connected, busy, quotaExceeded, unavailable, send, sendSettings } =
    socket;
  const members = socket.members.length ? socket.members : initialMembers;
  // Changed optimistically on tap; the server's echo (or a reconnect) has the last word.
  const [settings, setSettings] = useState(initialSettings);
  useEffect(() => {
    if (socket.roomSettings) setSettings(socket.roomSettings);
  }, [socket.roomSettings]);
  const free = settings.talk_mode === "free";
  const [draft, setDraft] = useState("");
  // null = no chip: the text decides (a name up front picks her, else both).
  const [target, setTarget] = useState<string | null>(null);
  const showDebug = new URLSearchParams(window.location.search).has("debug");
  const feed = useRef<HTMLDivElement>(null);

  useEffect(() => {
    feed.current?.scrollTo({ top: feed.current.scrollHeight });
  }, [messages, busy]);

  const seats = new Map(members.map((m, seat) => [m.slot, { ...m, seat }]));
  const title = members.map((m) => m.name).join(` ${strings.group_and}`);
  const typingSlot = typingSpeaker(messages);
  const typingLabel = typingSlot
    ? `${seats.get(typingSlot)?.name ?? ""} ${strings.chat_typing}`
    : `${title} ${strings.group_typing_many}`;

  function submit(event: React.FormEvent) {
    event.preventDefault();
    send(draft, target ? { target } : {});
    setDraft("");
  }

  function updateSettings(patch: Partial<GroupSettings>) {
    setSettings((prev) => ({ ...prev, ...patch }));
    sendSettings(patch);
  }

  if (unavailable) {
    return (
      <div className="center-state">
        <p>{strings.group_error}</p>
        <button type="button" className="header-link" onClick={onBack}>
          {strings.group_back}
        </button>
      </div>
    );
  }

  return (
    <div className="chat group-chat">
      <header className="chat-header">
        <button type="button" className="header-link" onClick={onBack}>
          {strings.group_back}
        </button>
        <div className="avatar-stack">
          {members.map((m) =>
            m.avatar_path ? (
              <img key={m.slot} src={m.avatar_path} alt="" />
            ) : (
              <div key={m.slot} className="avatar-placeholder">
                💗
              </div>
            ),
          )}
        </div>
        <div className="who">
          <div className="name">{title}</div>
          <div className={`state ${connected ? "online" : ""}`}>
            {connected ? strings.connected : strings.disconnected}
          </div>
        </div>
        {onLogout && (
          <button type="button" className="header-link" onClick={onLogout}>
            {strings.logout}
          </button>
        )}
      </header>

      <div className="chat-messages" ref={feed}>
        {messages.map((message, i) => {
          if (isPlaceholder(message)) return null;
          const seat = message.speaker ? seats.get(message.speaker) : undefined;
          return (
            <div
              key={i}
              className={`bubble ${message.role}${seat ? ` seat-${seat.seat}` : ""}`}
              dir="rtl"
            >
              {message.role === "assistant" && seat && (
                <span className="speaker-name">{seat.name}</span>
              )}
              <span>{message.content}</span>
            </div>
          );
        })}
        {isAwaitingReply(messages, busy) && <TypingIndicator label={typingLabel} />}
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
              aria-pressed={settings.response_length === n}
              className={settings.response_length === n ? "active" : ""}
              onClick={() => updateSettings({ response_length: n })}
            >
              {strings[`length_${n}`]}
            </button>
          ))}
          {/* Shows the mode the room is in; tapping switches to the other one. */}
          <button
            type="button"
            className={`talk-mode${free ? " active" : ""}`}
            onClick={() => updateSettings({ talk_mode: free ? "moderated" : "free" })}
          >
            {free ? strings.group_talk_free : strings.group_talk_moderated}
          </button>
        </div>
        <div className="length-row" role="radiogroup" aria-label={strings.group_target}>
          <span>{strings.group_target}</span>
          {[TARGET_ALL, ...members.map((m) => m.slot)].map((slot) => (
            <button
              type="button"
              key={slot}
              role="radio"
              aria-checked={target === slot}
              className={target === slot ? "active" : ""}
              // Tapping the chosen chip again goes back to "the text decides".
              onClick={() => setTarget(target === slot ? null : slot)}
            >
              {slot === TARGET_ALL ? strings.group_target_all : seats.get(slot)?.name}
            </button>
          ))}
        </div>
        <div className="compose">
          <input
            value={draft}
            // Explicit rtl, not "auto" — see Chat.tsx.
            dir="rtl"
            placeholder={strings.group_hint}
            onChange={(e) => setDraft(e.target.value)}
          />
          {/* Not disabled while they talk: sending interrupts the room. */}
          <button type="submit" disabled={!connected || !draft.trim()}>
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
