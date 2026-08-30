import type { Catalog, CompanionState, PersonaSpec, Plan, Subscription, User } from "./types";

/** Thrown for any non-OK response. `detail` is the server's error key (e.g.
 *  "invalid_credentials"), which the screens look up in `catalog.strings`. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
  }
}

/** Called when the server says the session is gone, so the app can drop to the
 *  login screen from anywhere rather than each caller handling 401. */
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep the status code */
    }
    // 401 anywhere means the cookie is gone or revoked. Fire the global
    // handler, but still throw so the calling screen stops its own flow.
    if (res.status === 401) onUnauthorized?.();
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const postJson = (url: string, body: unknown) =>
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const fetchCatalog = () => fetch("/api/catalog").then(json<Catalog>);

export const fetchCompanion = () => fetch("/api/companion").then(json<CompanionState>);

export function createCompanion(spec: PersonaSpec, reset = false) {
  return fetch("/api/companion", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...spec, reset }),
  }).then(json<{ ok: boolean; first_message: string | null }>);
}

export const fetchResponseLength = () =>
  fetch("/companion/response_length").then(json<{ level: number }>);

export const setResponseLength = (level: number) =>
  fetch("/companion/response_length", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level }),
  }).then(json<{ level: number }>);

// ── auth ───────────────────────────────────────────────────────────────────

export const fetchMe = () => fetch("/api/auth/me").then(json<{ user: User }>);

export const login = (email: string, password: string) =>
  postJson("/api/auth/login", { email, password }).then(json<{ user: User }>);

export const signup = (email: string, password: string) =>
  postJson("/api/auth/signup", { email, password }).then(json<{ user: User }>);

export const logout = () => postJson("/api/auth/logout", {}).then(json<{ ok: boolean }>);

export const forgotPassword = (email: string) =>
  postJson("/api/auth/forgot-password", { email }).then(json<{ ok: boolean }>);

export const resetPassword = (token: string, password: string) =>
  postJson("/api/auth/reset-password", { token, password }).then(json<{ ok: boolean }>);

// ── subscription ───────────────────────────────────────────────────────────

export const fetchPlans = () => fetch("/api/subscription/plans").then(json<{ plans: Plan[] }>);

export const fetchSubscription = () =>
  fetch("/api/subscription").then(json<Subscription>);

export const startCheckout = (planId: string) =>
  postJson("/api/subscription/checkout", { plan_id: planId }).then(json<{ url: string }>);

export const openBillingPortal = () =>
  postJson("/api/subscription/portal", {}).then(json<{ url: string }>);
