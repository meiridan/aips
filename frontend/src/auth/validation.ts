/** Client-side form validation.
 *
 *  Pure predicates returning string KEYS (resolved against the server's
 *  `catalog.strings`), in the same shape as the wizard's `stepComplete` /
 *  `toSpec`: the screens gate a disabled button on these rather than showing
 *  errors while someone is still typing.
 *
 *  This is a convenience, never a control — `maya/auth/accounts.py` and
 *  `maya/auth/passwords.py` repeat every check server-side.
 */

export const MIN_PASSWORD_LENGTH = 8;

// Matches the server's deliberately permissive rule: reject the obviously
// malformed, not the merely unusual.
const EMAIL_RE = /^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/;

export type FieldErrors = Partial<Record<"email" | "password" | "confirm", string>>;

export function validateEmail(email: string): string | null {
  const cleaned = email.trim();
  if (!cleaned) return "email_required";
  if (cleaned.length > 254 || !EMAIL_RE.test(cleaned)) return "email_invalid";
  return null;
}

export function validatePassword(password: string): string | null {
  if (!password) return "password_required";
  if (password.length < MIN_PASSWORD_LENGTH) return "password_too_short";
  if (password.length > 200) return "password_too_long";
  return null;
}

/** Login only checks that the fields are filled: rejecting a "too short"
 *  password here would tell someone their existing password is invalid. */
export function validateLogin(email: string, password: string): FieldErrors {
  const errors: FieldErrors = {};
  const emailError = validateEmail(email);
  if (emailError) errors.email = emailError;
  if (!password) errors.password = "password_required";
  return errors;
}

export function validateSignup(email: string, password: string): FieldErrors {
  const errors: FieldErrors = {};
  const emailError = validateEmail(email);
  if (emailError) errors.email = emailError;
  const passwordError = validatePassword(password);
  if (passwordError) errors.password = passwordError;
  return errors;
}

export function validateReset(password: string, confirm: string): FieldErrors {
  const errors: FieldErrors = {};
  const passwordError = validatePassword(password);
  if (passwordError) errors.password = passwordError;
  else if (password !== confirm) errors.confirm = "password_mismatch";
  return errors;
}

export function isEmpty(errors: FieldErrors): boolean {
  return Object.keys(errors).length === 0;
}
