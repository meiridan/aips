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
  strings: Record<string, string>;
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
}

export interface CompanionState {
  onboarded: boolean;
  name: string;
  avatar_path: string | null;
  locale: string;
  spec: PersonaSpec | null;
  response_length: number;
}
