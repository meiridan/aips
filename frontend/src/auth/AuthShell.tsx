import type { ReactNode } from "react";

interface Props {
  strings: Record<string, string>;
  title: string;
  subtitle?: string;
  children: ReactNode;
}

/** The framing every auth screen shares: the app's bloom background, branding,
 *  and a single centered card. Uses the same tokens and `.btn` vocabulary as
 *  the wizard so these read as part of the app, not a bolted-on login. */
export default function AuthShell({ strings, title, subtitle, children }: Props) {
  return (
    <div className="auth">
      <div className="auth-card">
        <div className="auth-brand">{strings.auth_brand}</div>
        <h1 className="auth-title">{title}</h1>
        {subtitle && <p className="auth-subtitle">{subtitle}</p>}
        {children}
      </div>
    </div>
  );
}
