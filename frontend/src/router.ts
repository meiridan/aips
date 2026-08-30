import { useCallback, useEffect, useState } from "react";

/** The app's client-side routes. */
export const ROUTES = {
  chat: "/",
  login: "/login",
  signup: "/signup",
  forgot: "/forgot-password",
  reset: "/reset-password",
  subscription: "/subscription",
} as const;

export type Route = (typeof ROUTES)[keyof typeof ROUTES];

/** Routes reachable while signed out. Everything else redirects to login. */
export const PUBLIC_ROUTES: string[] = [
  ROUTES.login,
  ROUTES.signup,
  ROUTES.forgot,
  ROUTES.reset,
];

/** Navigate without a reload, and tell the `useRoute` listeners. */
export function navigate(to: string, { replace = false } = {}) {
  if (replace) window.history.replaceState({}, "", to);
  else window.history.pushState({}, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/** Current path + query, re-rendering on back/forward and `navigate`.
 *
 *  Deliberately ~40 lines instead of a router dependency: the app needs five
 *  flat routes with no nesting, params, or loaders, and ships exactly two
 *  runtime dependencies today. `pushState` + `popstate` is the whole API a
 *  router would wrap here.
 *
 *  URLs became unavoidable with password reset — the link in that email has to
 *  survive being opened cold in a new tab.
 */
export function useRoute() {
  const read = () => ({
    path: window.location.pathname,
    query: new URLSearchParams(window.location.search),
  });
  const [state, setState] = useState(read);

  useEffect(() => {
    const onChange = () => setState(read());
    window.addEventListener("popstate", onChange);
    return () => window.removeEventListener("popstate", onChange);
  }, []);

  const go = useCallback((to: string, opts?: { replace?: boolean }) => navigate(to, opts), []);

  return { path: state.path, query: state.query, navigate: go };
}
