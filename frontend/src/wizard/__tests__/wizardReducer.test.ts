import { describe, expect, it } from "vitest";

import type { Catalog, Step } from "../../types";
import {
  initialState,
  specsEqual,
  stepComplete,
  toSpec,
  wizardReducer,
  type WizardState,
} from "../wizardReducer";

const catalog = {
  groups: {},
  age: { he: "גיל", min: 18, max: 55, default: 24 },
  steps: [
    { id: "style", he: "", groups: ["style"] },
    { id: "basics", he: "", groups: ["ethnicity"], age: true },
    { id: "character", he: "", groups: ["personality", "hobbies"] },
    { id: "summary", he: "", groups: [] },
  ] as Step[],
  strings: {},
} as unknown as Catalog;

const step = (id: string) => catalog.steps.find((s) => s.id === id)!;

function complete(): WizardState {
  let state = initialState(catalog);
  for (const [group, option] of [
    ["style", "realistic"],
    ["ethnicity", "arab"],
    ["personality", "caregiver"],
  ] as const) {
    state = wizardReducer(state, { type: "select", group, option });
  }
  return wizardReducer(state, { type: "setName", name: "מאיה" });
}

describe("initial state", () => {
  it("starts on the first step with the default age", () => {
    const state = initialState(catalog);
    expect(state.step).toBe(0);
    expect(state.draft.age).toBe(24);
    expect(state.draft.hobbies).toEqual([]);
  });
});

describe("navigation", () => {
  it("advances and goes back", () => {
    let state = initialState(catalog);
    state = wizardReducer(state, { type: "next", total: 4 });
    expect(state.step).toBe(1);
    state = wizardReducer(state, { type: "prev" });
    expect(state.step).toBe(0);
  });

  it("clamps at both ends", () => {
    let state = initialState(catalog);
    expect(wizardReducer(state, { type: "prev" }).step).toBe(0);
    for (let i = 0; i < 10; i++) state = wizardReducer(state, { type: "next", total: 4 });
    expect(state.step).toBe(3);
  });

  it("closes an open picker when the step changes", () => {
    let state = wizardReducer(initialState(catalog), {
      type: "openPicker",
      group: "personality",
    });
    expect(state.openPicker).toBe("personality");
    state = wizardReducer(state, { type: "next", total: 4 });
    expect(state.openPicker).toBeNull();
  });
});

describe("selection", () => {
  it("records a single choice and collapses the panel", () => {
    let state = wizardReducer(initialState(catalog), {
      type: "openPicker",
      group: "personality",
    });
    state = wizardReducer(state, {
      type: "select",
      group: "personality",
      option: "caregiver",
    });
    expect(state.draft.personality).toBe("caregiver");
    expect(state.openPicker).toBeNull();
  });

  it("toggles multi-choice values on and off", () => {
    let state = initialState(catalog);
    state = wizardReducer(state, { type: "toggle", group: "hobbies", option: "yoga" });
    state = wizardReducer(state, { type: "toggle", group: "hobbies", option: "cooking" });
    expect(state.draft.hobbies).toEqual(["yoga", "cooking"]);
    state = wizardReducer(state, { type: "toggle", group: "hobbies", option: "yoga" });
    expect(state.draft.hobbies).toEqual(["cooking"]);
  });

  it("hydrates from a saved spec", () => {
    const spec = { ...complete().draft, ethnicity: "asian" } as never;
    const state = wizardReducer(initialState(catalog), { type: "hydrate", spec });
    expect(state.draft.ethnicity).toBe("asian");
  });
});

describe("step gating", () => {
  it("blocks a step until its required group is chosen", () => {
    const state = initialState(catalog);
    expect(stepComplete(step("style"), state)).toBe(false);
    expect(
      stepComplete(
        step("style"),
        wizardReducer(state, { type: "select", group: "style", option: "anime" }),
      ),
    ).toBe(true);
  });

  it("treats hobbies as optional", () => {
    const state = wizardReducer(initialState(catalog), {
      type: "select",
      group: "personality",
      option: "caregiver",
    });
    expect(state.draft.hobbies).toEqual([]);
    expect(stepComplete(step("character"), state)).toBe(true);
  });

  it("requires a non-blank name on the summary step", () => {
    let state = initialState(catalog);
    expect(stepComplete(step("summary"), state)).toBe(false);
    state = wizardReducer(state, { type: "setName", name: "   " });
    expect(stepComplete(step("summary"), state)).toBe(false);
    state = wizardReducer(state, { type: "setName", name: "מאיה" });
    expect(stepComplete(step("summary"), state)).toBe(true);
  });
});

describe("toSpec", () => {
  it("is null while anything is missing", () => {
    expect(toSpec(catalog, initialState(catalog))).toBeNull();
  });

  it("trims the name and normalises empty details to null", () => {
    const state = wizardReducer(complete(), { type: "setName", name: "  מאיה  " });
    const spec = toSpec(catalog, state)!;
    expect(spec.name).toBe("מאיה");
    expect(spec.extra_details).toBeNull();
  });

  it("keeps real extra details", () => {
    const state = wizardReducer(complete(), {
      type: "setDetails",
      text: "  שונאת בוקר  ",
    });
    expect(toSpec(catalog, state)!.extra_details).toBe("שונאת בוקר");
  });
});

describe("specsEqual", () => {
  const base = {
    name: "מאיה",
    age: 24,
    style: "realistic",
    ethnicity: "arab",
    hair_style: "long",
    hair_color: "blue",
    eye_color: "hazel",
    body_type: "curvy",
    breast_size: "large",
    butt_size: "large",
    personality: "caregiver",
    relationship: "girlfriend",
    occupation: "nurse",
    clothing: "dress",
    voice_style: "soft",
    hobbies: ["yoga", "cooking"],
    extra_details: null,
  };

  it("is true for identical specs", () => {
    expect(specsEqual({ ...base }, { ...base })).toBe(true);
  });

  it("ignores hobby ordering", () => {
    expect(specsEqual({ ...base, hobbies: ["cooking", "yoga"] }, base)).toBe(true);
  });

  it("ignores whitespace on name and details", () => {
    expect(specsEqual({ ...base, name: "  מאיה  " }, base)).toBe(true);
    expect(specsEqual({ ...base, extra_details: "   " }, base)).toBe(true);
  });

  it("detects a changed option", () => {
    expect(specsEqual({ ...base, hair_color: "pink" }, base)).toBe(false);
  });

  it("detects a changed age, name, and hobby set", () => {
    expect(specsEqual({ ...base, age: 25 }, base)).toBe(false);
    expect(specsEqual({ ...base, name: "נועה" }, base)).toBe(false);
    expect(specsEqual({ ...base, hobbies: ["yoga"] }, base)).toBe(false);
  });

  it("detects added extra details", () => {
    expect(specsEqual({ ...base, extra_details: "שונאת בוקר" }, base)).toBe(false);
  });

  it("is false when either side is missing", () => {
    expect(specsEqual(null, base)).toBe(false);
    expect(specsEqual(base, null)).toBe(false);
  });
});
