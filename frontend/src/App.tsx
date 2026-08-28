import { useCallback, useEffect, useState } from "react";

import { fetchCatalog, fetchCompanion } from "./api";
import Chat from "./chat/Chat";
import type { Catalog, CompanionState } from "./types";
import Wizard from "./wizard/Wizard";

/** The creation flow is always the first screen, even for a companion that has
 *  already been brought to life — the wizard opens prefilled with her, and its
 *  final button either continues to chat or re-creates her (see Wizard.tsx).
 *  Chat is reached by going through it, never by landing straight on it. */
export default function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [companion, setCompanion] = useState<CompanionState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inChat, setInChat] = useState(false);

  const load = useCallback(
    (thenChat: boolean) => {
      Promise.all([fetchCatalog(), fetchCompanion()])
        .then(([c, state]) => {
          setCatalog(c);
          setCompanion(state);
          if (thenChat) setInChat(true);
        })
        .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    },
    [],
  );

  useEffect(() => load(false), [load]);

  if (error) {
    return (
      <div className="center-state">
        <p>משהו השתבש בטעינה.</p>
        <p dir="ltr" style={{ fontSize: 13 }}>
          {error}
        </p>
      </div>
    );
  }

  if (!catalog || !companion) {
    return (
      <div className="center-state">
        <div className="spinner" />
      </div>
    );
  }

  return (
    <div className="app">
      {inChat ? (
        <Chat companion={companion} strings={catalog.strings} />
      ) : (
        <Wizard
          catalog={catalog}
          existing={companion.spec}
          onboarded={companion.onboarded}
          // Re-fetch so the chat header shows the freshly created name/avatar.
          onDone={() => load(true)}
          onSkip={() => setInChat(true)}
        />
      )}
    </div>
  );
}
