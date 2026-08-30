export interface Option {
  id: string;
  he: string;
  en: string;
  asset: string | null;
  emoji: string | null;
  color: string | null;
  extra: Record<string, unknown>;
}

export interface Group {
  id: string;
  he: string;
  kind: "tiles" | "emoji";
  multi: boolean;
  options: Option[];
}

/** One ready-made companion on the opening gallery. Mirrors catalog.Preset. */
export interface Preset {
  id: string;
  name: string;
  /** Trait title without her name — render as "{name} — {tagline}". */
  tagline: string;
  bio: string;
  /** First-person line the voice preview speaks when no recording exists. */
  voice_line: string;
  badge: "new" | "trending" | "online" | null;
  spec: Record<string, unknown>;
  portrait: string;
  gallery: string[];
  /** Optional recorded sample; 404 is normal (see maya/media/README.md). */
  voice: string;
}

export interface Step {
  id: string;
  he: string;
  groups: string[];
  age?: boolean;
}

export interface Catalog {
  groups: Record<string, Group>;
  age: { he: string; min: number; max: number; default: number };
  steps: Step[];
  presets: Preset[];
  /** Group ids the gallery offers as filter chips, in order. */
  preset_filters?: string[];
  strings: Record<string, string>;
  /** Which sign-in methods the server actually has configured.
   *  `dev_login` means the server is bypassing auth (local DEV_AUTOLOGIN). */
  auth: { google: boolean; dev_login?: boolean };
}

/** Mirrors maya.companions.persona_spec.PersonaSpec. */
export interface PersonaSpec {
  name: string;
  age: number;
  style: string;
  ethnicity: string;
  hair_style: string;
  hair_color: string;
  eye_color: string;
  body_type: string;
  breast_size: string;
  butt_size: string;
  personality: string;
  relationship: string;
  occupation: string;
  clothing: string;
  voice_style: string;
  hobbies: string[];
  extra_details?: string | null;
  /** Set when she came from the gallery rather than a wizard run. */
  preset?: string | null;
}

export interface CompanionState {
  onboarded: boolean;
  name: string;
  avatar_path: string | null;
  locale: string;
  spec: PersonaSpec | null;
  response_length: number;
}

export interface User {
  id: string;
  email: string | null;
  name: string;
  email_verified: boolean;
}

export interface Plan {
  id: string;
  he: string;
  description: string;
  price: number;
  currency: string;
  interval: "month" | "year" | null;
  features: string[];
}

export interface Subscription {
  plan_id: string;
  status: string;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  manageable: boolean;
}
