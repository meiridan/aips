import type { Catalog, PersonaSpec, Step } from "../types";

/** Groups the user may leave empty; everything else gates the "next" button. */
const OPTIONAL_GROUPS = new Set(["hobbies"]);

export interface WizardState {
  step: number;
  draft: Partial<PersonaSpec>;
  /** id of the character-step picker whose option panel is expanded. */
  openPicker: string | null;
  showDetails: boolean;
  avatar: string | null;
}

export type WizardAction =
  | { type: "select"; group: string; option: string }
  | { type: "toggle"; group: string; option: string }
  | { type: "setAge"; age: number }
  | { type: "setName"; name: string }
  | { type: "setDetails"; text: string }
  | { type: "openPicker"; group: string | null }
  | { type: "toggleDetails" }
  | { type: "setAvatar"; url: string | null }
  | { type: "next"; total: number }
  | { type: "prev" }
  | { type: "hydrate"; spec: PersonaSpec };

export function initialState(catalog: Catalog): WizardState {
  return {
    step: 0,
    draft: { age: catalog.age.default, hobbies: [] },
    openPicker: null,
    showDetails: false,
    avatar: null,
  };
}

export function wizardReducer(state: WizardState, action: WizardAction): WizardState {
  switch (action.type) {
    case "select":
      return {
        ...state,
        draft: { ...state.draft, [action.group]: action.option },
        // Picking closes the panel — the comp collapses it right after a choice.
        openPicker: null,
      };

    case "toggle": {
      const current = ((state.draft as Record<string, unknown>)[action.group] ??
        []) as string[];
      const next = current.includes(action.option)
        ? current.filter((id) => id !== action.option)
        : [...current, action.option];
      return { ...state, draft: { ...state.draft, [action.group]: next } };
    }

    case "setAge":
      return { ...state, draft: { ...state.draft, age: action.age } };

    case "setName":
      return { ...state, draft: { ...state.draft, name: action.name } };

    case "setDetails":
      return { ...state, draft: { ...state.draft, extra_details: action.text } };

    case "openPicker":
      return {
        ...state,
        openPicker: state.openPicker === action.group ? null : action.group,
      };

    case "toggleDetails":
      return { ...state, showDetails: !state.showDetails };

    case "setAvatar":
      return { ...state, avatar: action.url };

    case "next":
      return {
        ...state,
        step: Math.min(state.step + 1, action.total - 1),
        openPicker: null,
      };

    case "prev":
      return { ...state, step: Math.max(state.step - 1, 0), openPicker: null };

    case "hydrate":
      return { ...state, draft: { ...action.spec } };

    default:
      return state;
  }
}

/** True when the current step has everything the backend will demand. */
export function stepComplete(step: Step, state: WizardState): boolean {
  const draft = state.draft as Record<string, unknown>;

  for (const group of step.groups) {
    if (OPTIONAL_GROUPS.has(group)) continue;
    if (!draft[group]) return false;
  }
  if (step.id === "summary") {
    return String(draft.name ?? "").trim().length > 0;
  }
  return true;
}

/** Field-by-field spec equality, so an untouched wizard doesn't re-create her. */
export function specsEqual(a: PersonaSpec | null, b: PersonaSpec | null): boolean {
  if (!a || !b) return false;
  const norm = (spec: PersonaSpec) => ({
    ...spec,
    name: spec.name.trim(),
    hobbies: [...(spec.hobbies ?? [])].sort(),
    extra_details: spec.extra_details?.trim() || null,
  });
  const x = norm(a) as Record<string, unknown>;
  const y = norm(b) as Record<string, unknown>;
  const keys = new Set([...Object.keys(x), ...Object.keys(y)]);
  for (const key of keys) {
    const xv = x[key];
    const yv = y[key];
    if (Array.isArray(xv) || Array.isArray(yv)) {
      if (JSON.stringify(xv ?? []) !== JSON.stringify(yv ?? [])) return false;
    } else if ((xv ?? null) !== (yv ?? null)) {
      return false;
    }
  }
  return true;
}

/** The complete spec, or null while anything is still missing. */
export function toSpec(catalog: Catalog, state: WizardState): PersonaSpec | null {
  if (!catalog.steps.every((step) => stepComplete(step, state))) return null;
  const draft = state.draft as PersonaSpec;
  return {
    ...draft,
    name: draft.name.trim(),
    hobbies: draft.hobbies ?? [],
    extra_details: draft.extra_details?.trim() || null,
  };
}
