import { useState } from "react";

import { ApiError, forgotPassword } from "../api";
import { ROUTES, navigate } from "../router";
import AuthShell from "./AuthShell";
import Field from "./Field";
import { validateEmail } from "./validation";

interface Props {
  strings: Record<string, string>;
}

export default function ForgotPasswordScreen({ strings: s }: Props) {
  const [email, setEmail] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting) return;

    const problem = validateEmail(email);
    setFieldError(problem);
    if (problem) return;

    setSubmitting(true);
    setFormError(null);
    try {
      await forgotPassword(email);
      // Shown whether or not that address has an account. The server answers
      // 202 either way; the screen must not narrow it down.
      setSent(true);
    } catch (err) {
      // Only rate limiting can fail here — anything else would leak.
      const key = err instanceof ApiError ? err.detail : "auth_error";
      setFormError(s[key] ?? s.auth_error);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell strings={s} title={s.forgot_title} subtitle={sent ? undefined : s.forgot_intro}>
      {sent ? (
        <p className="auth-notice">{s.forgot_sent}</p>
      ) : (
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
            error={fieldError ? s[fieldError] : undefined}
            onChange={setEmail}
          />
          {formError && <p className="form-error">{formError}</p>}
          <button type="submit" className="btn btn-primary auth-submit" disabled={submitting}>
            {submitting ? s.forgot_submitting : s.forgot_submit}
          </button>
        </form>
      )}

      <button type="button" className="auth-link auth-footer" onClick={() => navigate(ROUTES.login)}>
        {s.back_to_login}
      </button>
    </AuthShell>
  );
}
