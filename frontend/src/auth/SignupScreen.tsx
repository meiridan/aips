import { useState } from "react";

import { ApiError, signup } from "../api";
import { ROUTES, navigate } from "../router";
import type { User } from "../types";
import AuthShell from "./AuthShell";
import Field from "./Field";
import { isEmpty, validateSignup, type FieldErrors } from "./validation";

interface Props {
  strings: Record<string, string>;
  /** False when the server has no Google OAuth credentials. */
  googleEnabled?: boolean;
  onSignedIn: (user: User) => void;
}

export default function SignupScreen({ strings: s, googleEnabled = false, onSignedIn }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting) return;

    const errors = validateSignup(email, password);
    setFieldErrors(errors);
    if (!isEmpty(errors)) return;

    setSubmitting(true);
    setFormError(null);
    try {
      const { user } = await signup(email, password);
      onSignedIn(user);
    } catch (err) {
      const key = err instanceof ApiError ? err.detail : "auth_error";
      setFormError(s[key] ?? s.auth_error);
      setSubmitting(false);
    }
  }

  return (
    <AuthShell strings={s} title={s.signup_title}>
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
          placeholder={s.password_placeholder}
          value={password}
          autoComplete="new-password"
          disabled={submitting}
          error={fieldErrors.password && s[fieldErrors.password]}
          onChange={setPassword}
        />

        {formError && <p className="form-error">{formError}</p>}

        <button type="submit" className="btn btn-primary auth-submit" disabled={submitting}>
          {submitting ? s.signup_submitting : s.signup_submit}
        </button>
      </form>

      <button type="button" className="auth-link auth-footer" onClick={() => navigate(ROUTES.login)}>
        {s.to_login}
      </button>
    </AuthShell>
  );
}
