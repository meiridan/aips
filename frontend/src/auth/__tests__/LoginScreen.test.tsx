import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api";
import LoginScreen from "../LoginScreen";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, login: vi.fn() };
});

const { login } = await import("../../api");
const loginMock = vi.mocked(login);

/** A stand-in for the server's catalog.strings: identity-ish, so assertions
 *  read as the key rather than depending on the Hebrew copy. */
const strings = new Proxy({} as Record<string, string>, {
  get: (_t, key: string) => `[${key}]`,
  has: () => true,
});

afterEach(cleanup);

function renderScreen(props: Partial<Parameters<typeof LoginScreen>[0]> = {}) {
  const onSignedIn = vi.fn();
  render(
    <LoginScreen strings={strings} googleEnabled onSignedIn={onSignedIn} {...props} />,
  );
  return { onSignedIn };
}

const emailInput = () => screen.getByLabelText("[email_label]");
const passwordInput = () => screen.getByLabelText("[password_label]");
const submitButton = () => screen.getByRole("button", { name: "[login_submit]" });

function fill(email = "a@b.co", password = "hunter2000") {
  fireEvent.change(emailInput(), { target: { value: email } });
  fireEvent.change(passwordInput(), { target: { value: password } });
}

describe("rendering", () => {
  it("shows both ways in", () => {
    renderScreen();
    expect(screen.getByText("[google_continue]")).toBeTruthy();
    expect(emailInput()).toBeTruthy();
    expect(passwordInput()).toBeTruthy();
    expect(submitButton()).toBeTruthy();
  });

  it("offers forgot-password and sign-up", () => {
    renderScreen();
    expect(screen.getByRole("button", { name: "[forgot_link]" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "[to_signup]" })).toBeTruthy();
  });

  it("points Continue with Google at the server's OAuth start", () => {
    // A client-side redirect would lose the state/PKCE cookies the server sets.
    renderScreen();
    const link = screen.getByText("[google_continue]").closest("a");
    expect(link?.getAttribute("href")).toBe("/auth/google/start");
  });

  it("hides Google entirely when the server has no credentials", () => {
    // Offering a button that can only 503 is worse than not offering it.
    renderScreen({ googleEnabled: false });
    expect(screen.queryByText("[google_continue]")).toBeNull();
    expect(screen.queryByText("[auth_divider]")).toBeNull();
    // The email path is untouched.
    expect(emailInput()).toBeTruthy();
  });

  it("shows an error carried back on the URL", () => {
    renderScreen({ urlError: "google_not_configured" });
    expect(screen.getByText("[google_not_configured]")).toBeTruthy();
  });

  it("notes an expired session, but only when one existed", () => {
    renderScreen({ expired: true });
    expect(screen.getByText("[session_expired]")).toBeTruthy();
    cleanup();
    renderScreen();
    expect(screen.queryByText("[session_expired]")).toBeNull();
  });
});

describe("validation", () => {
  it("does not call the API when the form is empty", () => {
    renderScreen();
    fireEvent.click(submitButton());
    expect(loginMock).not.toHaveBeenCalled();
    expect(screen.getByText("[email_required]")).toBeTruthy();
    expect(screen.getByText("[password_required]")).toBeTruthy();
  });

  it("rejects a malformed address before hitting the network", () => {
    renderScreen();
    fill("nope", "hunter2000");
    fireEvent.click(submitButton());
    expect(loginMock).not.toHaveBeenCalled();
    expect(screen.getByText("[email_invalid]")).toBeTruthy();
  });
});

describe("submission", () => {
  it("signs in on success", async () => {
    const user = { id: "1", email: "a@b.co", name: "A", email_verified: false };
    loginMock.mockResolvedValueOnce({ user });
    const { onSignedIn } = renderScreen();

    fill();
    fireEvent.click(submitButton());

    await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith(user));
    expect(loginMock).toHaveBeenCalledWith("a@b.co", "hunter2000");
  });

  it("shows the server's message on a failed login", async () => {
    loginMock.mockRejectedValueOnce(new ApiError(401, "invalid_credentials"));
    const { onSignedIn } = renderScreen();

    fill();
    fireEvent.click(submitButton());

    await waitFor(() => expect(screen.getByText("[invalid_credentials]")).toBeTruthy());
    expect(onSignedIn).not.toHaveBeenCalled();
  });

  it("surfaces rate limiting", async () => {
    loginMock.mockRejectedValueOnce(new ApiError(429, "too_many_requests"));
    renderScreen();
    fill();
    fireEvent.click(submitButton());
    await waitFor(() => expect(screen.getByText("[too_many_requests]")).toBeTruthy());
  });

  it("falls back to a generic message when the network dies", async () => {
    loginMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    renderScreen();
    fill();
    fireEvent.click(submitButton());
    await waitFor(() => expect(screen.getByText("[auth_error]")).toBeTruthy());
  });

  it("shows a loading state and disables the form while in flight", async () => {
    let release: (value: { user: never }) => void = () => {};
    loginMock.mockReturnValueOnce(new Promise((resolve) => (release = resolve as never)));
    renderScreen();

    fill();
    fireEvent.click(submitButton());

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "[login_submitting]" })).toBeTruthy(),
    );
    expect((emailInput() as HTMLInputElement).disabled).toBe(true);
    expect((passwordInput() as HTMLInputElement).disabled).toBe(true);
    release({ user: { id: "1", email: "a@b.co", name: "A", email_verified: false } as never });
  });

  it("does not submit twice", async () => {
    loginMock.mockReturnValueOnce(new Promise(() => {}));
    renderScreen();

    fill();
    const button = submitButton();
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(loginMock).toHaveBeenCalledTimes(1));
  });
});
