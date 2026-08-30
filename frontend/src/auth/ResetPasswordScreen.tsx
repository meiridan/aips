import { useState } from "react";

import { ApiError, resetPassword } from "../api";
import { ROUTES, navigate } from "../router";
import AuthShell from "./AuthShell";
import Field from "./Field";
import { isEmpty, validateReset, type FieldErrors } from "./validation";

interface Props {
  strings: Record<string, string>;
  /** From the emailed link's ?token=. */
  token: string | null;
}

export default function ResetPasswordScreen({ strings: s, token }: Props) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting || !token) return;

    const errors = validateReset(password, confirm);
    setFieldErrors(errors);
    if (!isEmpty(errors)) return;

    setSubmitting(true);
    setFormError(null);
    try {
      await resetPassword(token, password);
      setDone(true);
    } catch (err) {
      const key = err instanceof ApiError ? err.detail : "auth_error";
      setFormError(s[key] ?? s.auth_error);
      setSubmitting(false);
    }
  }

  // A link with no token is a mangled email, not a form to fill in.
  if (!token) {
    return (
      <AuthShell strings={s} title={s.reset_title}>
        <p className="form-error">{s.invalid_or_expired_token}</p>
        <button type="button" className="btn btn-primary auth-submit" onClick={() => navigate(ROUTES.forgot)}>
          {s.forgot_submit}
        </button>
      </AuthShell>
    );
  }

  if (done) {
    return (
      <AuthShell strings={s} title={s.reset_title}>
        <p className="auth-notice">{s.reset_done}</p>
        <button type="button" className="btn btn-primary auth-submit" onClick={() => navigate(ROUTES.login)}>
          {s.login_submit}
        </button>
      </AuthShell>
    );
  }

  return (
    <AuthShell strings={s} title={s.reset_title}>
      <form onSubmit={submit} noValidate>
        <Field
          id="password"
          type="password"
          label={s.password_label}
          placeholder={s.password_placeholder}
          value={password}
          autoComplete="new-password"
          autoFocus
          disabled={submitting}
          error={fieldErrors.password && s[fieldErrors.password]}
          onChange={setPassword}
        />
        <Field
          id="confirm"
          type="password"
          label={s.password_confirm_label}
          value={confirm}
          autoComplete="new-password"
          disabled={submitting}
          error={fieldErrors.confirm && s[fieldErrors.confirm]}
          onChange={setConfirm}
        />
        {formError && <p className="form-error">{formError}</p>}
        <button type="submit" className="btn btn-primary auth-submit" disabled={submitting}>
          {submitting ? s.reset_submitting : s.reset_submit}
        </button>
      </form>

      <button type="button" className="auth-link auth-footer" onClick={() => navigate(ROUTES.login)}>
        {s.back_to_login}
      </button>
    </AuthShell>
  );
}
