import { useState } from "react";

import { ApiError, login } from "../api";
import { ROUTES, navigate } from "../router";
import type { User } from "../types";
import AuthShell from "./AuthShell";
import Field from "./Field";
import { isEmpty, validateLogin, type FieldErrors } from "./validation";

interface Props {
  strings: Record<string, string>;
  /** Set when a live session was lost rather than never having existed. */
  expired?: boolean;
  /** False when the server has no Google OAuth credentials. */
  googleEnabled?: boolean;
  /** An error key carried back on the URL, e.g. from a failed OAuth redirect. */
  urlError?: string | null;
  onSignedIn: (user: User) => void;
}

export default function LoginScreen({
  strings: s,
  expired,
  googleEnabled = false,
  urlError,
  onSignedIn,
}: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(
    urlError ? (s[urlError] ?? s.auth_error) : null,
  );
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    // `submitting` is the duplicate-submission guard: the button is disabled
    // and this returns early even if a second submit slips through.
    if (submitting) return;

    const errors = validateLogin(email, password);
    setFieldErrors(errors);
    if (!isEmpty(errors)) return;

    setSubmitting(true);
    setFormError(null);
    try {
      const { user } = await login(email, password);
      onSignedIn(user);
    } catch (err) {
      // The server answers the same way for an unknown address and a wrong
      // password; showing its key verbatim keeps it that way.
      const key = err instanceof ApiError ? err.detail : "auth_error";
      setFormError(s[key] ?? s.auth_error);
      setSubmitting(false);
    }
  }

  return (
    <AuthShell strings={s} title={s.login_title} subtitle={s.login_subtitle}>
      {/* Hidden when the server has no OAuth credentials — offering a button
          that can only fail is worse than not offering it. */}
      {googleEnabled && (
        <>
          <a className="btn btn-google" href="/auth/google/start">
            <span className="google-mark" aria-hidden="true">
              G
            </span>
            {s.google_continue}
          </a>

          <div className="auth-divider">
            <span>{s.auth_divider}</span>
          </div>
        </>
      )}

      <form onSubmit={submit} noValidate>
        <Field
          id="email"
          type="email"
          label={s.email_label}
          placeholder={s.email_placeholder}
          value={email}
          autoComplete="email"
          autoFocus
          disabled={submitting}
          error={fieldErrors.email && s[fieldErrors.email]}
          onChange={setEmail}
        />
        <Field
          id="password"
          type="password"
          label={s.password_label}
          value={password}
          autoComplete="current-password"
          disabled={submitting}
          error={fieldErrors.password && s[fieldErrors.password]}
          onChange={setPassword}
        />

        <button type="button" className="auth-link" onClick={() => navigate(ROUTES.forgot)}>
          {s.forgot_link}
        </button>

        {expired && !formError && <p className="form-warning">{s.session_expired}</p>}
        {formError && <p className="form-error">{formError}</p>}

        <button type="submit" className="btn btn-primary auth-submit" disabled={submitting}>
          {submitting ? s.login_submitting : s.login_submit}
        </button>
      </form>

      <button type="button" className="auth-link auth-footer" onClick={() => navigate(ROUTES.signup)}>
        {s.to_signup}
      </button>
    </AuthShell>
  );
}
