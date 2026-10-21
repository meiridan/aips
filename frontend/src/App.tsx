import { useCallback, useEffect, useState } from "react";

import { fetchCatalog, fetchCompanion } from "./api";
import ForgotPasswordScreen from "./auth/ForgotPasswordScreen";
import LoginScreen from "./auth/LoginScreen";
import ResetPasswordScreen from "./auth/ResetPasswordScreen";
import SignupScreen from "./auth/SignupScreen";
import { useSession } from "./auth/useSession";
import SubscriptionScreen from "./billing/SubscriptionScreen";
import Chat from "./chat/Chat";
import GroupChat from "./chat/GroupChat";
import PresetGallery from "./presets/PresetGallery";
import PresetProfile from "./presets/PresetProfile";
import { PUBLIC_ROUTES, ROUTES, useRoute } from "./router";
import type { Catalog, CompanionState, Preset } from "./types";
import Wizard from "./wizard/Wizard";

/** Route + auth gate.
 *
 *  Signed in, the creation flow is the first screen even for a companion who
 *  already exists. It opens on the gallery of ready-made companions: picking
 *  one creates her and goes straight to chat. "Build your own" drops into the
 *  six-step wizard, whose final button either continues to chat or re-creates
 *  her (see Wizard.tsx).
 *
 *  When the server reports `auth.single_user` (SINGLE_USER, the current default)
 *  there is no login flow at all: `/api/auth/me` always answers, so the status is
 *  always "authed", the auth screens below are unreachable, and the logout button
 *  is hidden everywhere. `auth.dev_login` (local DEV_AUTOLOGIN) is the older,
 *  local-only version of the same bypass.
 */
export default function App() {
  const { path, query, navigate } = useRoute();
  const session = useSession();

  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [companion, setCompanion] = useState<CompanionState | null>(null);
  const [error, setError] = useState<string | null>(null);
  // null = nothing picked yet, so the opening screen is the preset gallery.
  const [mode, setMode] = useState<"presets" | "wizard" | "chat" | null>(null);
  const [viewing, setViewing] = useState<Preset | null>(null);

  // The catalog is public: the login screen needs its Hebrew strings before
  // anyone is signed in.
  useEffect(() => {
    fetchCatalog()
      .then(setCatalog)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const loadCompanion = useCallback((thenChat: boolean) => {
    fetchCompanion()
      .then((state) => {
        setCompanion(state);
        if (thenChat) setMode("chat");
      })
      .catch((err) => {
        // A 401 is handled globally by useSession; don't also show it here.
        if (err instanceof Error && err.message !== "not_authenticated") {
          setError(err.message);
        }
      });
  }, []);

  useEffect(() => {
    if (session.status !== "authed") {
      setCompanion(null);
      setMode(null);
      setViewing(null);
      return;
    }
    loadCompanion(false);
  }, [session.status, loadCompanion]);

  // Keep the URL honest about what is actually on screen.
  useEffect(() => {
    if (session.status === "loading") return;
    const isPublic = PUBLIC_ROUTES.includes(path);
    if (session.status === "anon" && !isPublic) {
      navigate(ROUTES.login, { replace: true });
    } else if (session.status === "authed" && isPublic) {
      navigate(ROUTES.chat, { replace: true });
    }
  }, [session.status, path, navigate]);

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

  if (!catalog || session.status === "loading") {
    return (
      <div className="center-state">
        <div className="spinner" />
      </div>
    );
  }

  const s = catalog.strings;
  // The gallery is the opening screen; the wizard is opt-in from its ✨ tile.
  const screen = mode ?? "presets";
  // No login flow means no logout: the screens hide the button when it is absent.
  const onLogout = catalog.auth?.single_user ? undefined : session.logout;

  if (session.status === "anon") {
    switch (path) {
      case ROUTES.signup:
        return (
          <SignupScreen
            strings={s}
            googleEnabled={catalog.auth?.google ?? false}
            onSignedIn={session.signedIn}
          />
        );
      case ROUTES.forgot:
        return <ForgotPasswordScreen strings={s} />;
      case ROUTES.reset:
        return <ResetPasswordScreen strings={s} token={query.get("token")} />;
      default:
        return (
          <LoginScreen
            strings={s}
            expired={session.expired}
            googleEnabled={catalog.auth?.google ?? false}
            urlError={query.get("error")}
            onSignedIn={session.signedIn}
          />
        );
    }
  }

  if (path === ROUTES.subscription) {
    return (
      <SubscriptionScreen
        strings={s}
        justReturnedFromCheckout={query.get("checkout") === "success"}
        onLogout={onLogout}
      />
    );
  }

  if (!companion) {
    return (
      <div className="center-state">
        <div className="spinner" />
      </div>
    );
  }

  // The shared room needs her to exist first: it is "her and her friend".
  const groupAvailable = (catalog.features?.group_chat ?? false) && companion.onboarded;

  if (path === ROUTES.group && groupAvailable) {
    return (
      <div className="app">
        <GroupChat
          strings={s}
          onLogout={onLogout}
          onBack={() => {
            setMode("chat");
            navigate(ROUTES.chat);
          }}
        />
      </div>
    );
  }

  if (screen === "chat") {
    return (
      <div className="app">
        <Chat
          companion={companion}
          strings={s}
          onLogout={onLogout}
          onOpenGroup={groupAvailable ? () => navigate(ROUTES.group) : undefined}
        />
      </div>
    );
  }

  if (screen === "wizard") {
    return (
      <div className="app">
        <Wizard
          catalog={catalog}
          existing={companion.spec}
          onboarded={companion.onboarded}
          // Re-fetch so the chat header shows the freshly created name/avatar.
          onDone={() => loadCompanion(true)}
          onSkip={() => setMode("chat")}
          onBack={() => setMode("presets")}
          onLogout={onLogout}
        />
      </div>
    );
  }

  return (
    <div className="app">
      {viewing ? (
        <PresetProfile
          catalog={catalog}
          preset={viewing}
          onboarded={companion.onboarded}
          onBack={() => setViewing(null)}
          // Re-fetch so the chat header shows the freshly created name/avatar.
          onStarted={() => loadCompanion(true)}
        />
      ) : (
        <PresetGallery
          catalog={catalog}
          user={session.user}
          onOpen={setViewing}
          onCustom={() => setMode("wizard")}
          onLogout={onLogout}
        />
      )}
    </div>
  );
}
