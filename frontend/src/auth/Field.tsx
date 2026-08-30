interface Props {
  id: string;
  label: string;
  type: "email" | "password";
  value: string;
  placeholder?: string;
  error?: string;
  autoComplete?: string;
  autoFocus?: boolean;
  disabled?: boolean;
  onChange: (value: string) => void;
}

/** A labelled input with its error message.
 *
 *  Email and password are always latin script, so they get `dir="ltr"` inside
 *  the RTL page — otherwise the caret and any punctuation jump around.
 */
export default function Field({
  id,
  label,
  type,
  value,
  placeholder,
  error,
  autoComplete,
  autoFocus,
  disabled,
  onChange,
}: Props) {
  return (
    <div className="auth-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type={type}
        dir="ltr"
        value={value}
        placeholder={placeholder}
        autoComplete={autoComplete}
        autoFocus={autoFocus}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      {error && (
        <p className="form-error" id={`${id}-error`}>
          {error}
        </p>
      )}
    </div>
  );
}
