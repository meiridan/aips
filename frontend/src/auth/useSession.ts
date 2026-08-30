import { useCallback, useEffect, useState } from "react";

import { ApiError, fetchMe, logout as logoutRequest, setUnauthorizedHandler } from "../api";
import type { User } from "../types";

export type SessionStatus = "loading" | "anon" | "authed";

/** Who is signed in, for the whole app.
 *
 *  One `/api/auth/me` call at boot decides between the login screen and the
 *  app. Registers the api client's 401 handler so a session that dies mid-use
 *  (revoked, expired, server restarted) drops straight to "anon" instead of
 *  leaving a screen stuck on a spinner.
 */
export function useSession() {
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [expired, setExpired] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const { user } = await fetchMe();
      setUser(user);
      setStatus("authed");
    } catch (err) {
      // A 401 here is the normal signed-out case, not an error worth showing.
      if (!(err instanceof ApiError) || err.status !== 401) {
        // Network/server trouble: still unauthenticated as far as the UI goes.
      }
      setUser(null);
      setStatus("anon");
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser((current) => {
        // Only call it "expired" if we thought we were signed in — a 401 on the
        // login screen is just a failed attempt.
        if (current) setExpired(true);
        return null;
      });
      setStatus("anon");
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signedIn = useCallback((next: User) => {
    setUser(next);
    setExpired(false);
    setStatus("authed");
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      setUser(null);
      setExpired(false);
      setStatus("anon");
    }
  }, []);

  return { status, user, expired, refresh, signedIn, logout };
}
