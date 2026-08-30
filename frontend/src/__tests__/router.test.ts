import { beforeEach, describe, expect, it } from "vitest";

import { PUBLIC_ROUTES, ROUTES, navigate } from "../router";

describe("navigate", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("changes the path without a reload", () => {
    navigate(ROUTES.login);
    expect(window.location.pathname).toBe("/login");
  });

  it("preserves a query string", () => {
    navigate("/reset-password?token=abc123");
    expect(window.location.pathname).toBe("/reset-password");
    expect(new URLSearchParams(window.location.search).get("token")).toBe("abc123");
  });

  it("pushes history by default so back works", () => {
    const before = window.history.length;
    navigate(ROUTES.signup);
    expect(window.history.length).toBeGreaterThanOrEqual(before);
  });

  it("notifies listeners", () => {
    let fired = 0;
    const listener = () => (fired += 1);
    window.addEventListener("popstate", listener);
    navigate(ROUTES.forgot);
    window.removeEventListener("popstate", listener);
    expect(fired).toBe(1);
  });
});

describe("route table", () => {
  it("keeps the reset link public", () => {
    // The reset link is opened cold from an email, by definition signed out.
    expect(PUBLIC_ROUTES).toContain(ROUTES.reset);
    expect(PUBLIC_ROUTES).toContain(ROUTES.forgot);
  });

  it("does not expose chat or subscription publicly", () => {
    expect(PUBLIC_ROUTES).not.toContain(ROUTES.chat);
    expect(PUBLIC_ROUTES).not.toContain(ROUTES.subscription);
  });
});
