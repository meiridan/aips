import { useMemo, useReducer, useState } from "react";

import { createCompanion } from "../api";
import type { Catalog, PersonaSpec } from "../types";
import AgeSlider from "./AgeSlider";
import EmojiGrid from "./EmojiGrid";
import PickerCard from "./PickerCard";
import Stepper from "./Stepper";
import Summary from "./Summary";
import TileGrid from "./TileGrid";
import {
  initialState,
  specsEqual,
  stepComplete,
  toSpec,
  wizardReducer,
} from "./wizardReducer";

interface Props {
  catalog: Catalog;
  existing: PersonaSpec | null;
  /** She has already been brought to life — going through again is optional. */
  onboarded: boolean;
  /** A new companion was created; reload state and enter chat. */
  onDone: () => void;
  /** Nothing was changed — enter chat without touching her. */
  onSkip: () => void;
  /** Sign out — reachable before onboarding, where there is no chat header. */
  /** Omitted in single-user mode: nothing to log out of, so no button. */
  onLogout?: () => void;
  /** Back to the gallery of ready-made companions. */
  onBack: () => void;
}

/** Tile proportions per group, matching the reference comps. */
const TILE_SIZE: Record<string, "wide" | "short" | "default"> = {
  style: "wide",
  eye_color: "short",
};

export default function Wizard({
  catalog,
  existing,
  onboarded,
  onDone,
  onSkip,
  onLogout,
  onBack,
}: Props) {
  const [state, dispatch] = useReducer(
    wizardReducer,
    catalog,
    (c) => {
      const base = initialState(c);
      return existing ? { ...base, draft: { ...existing } } : base;
    },
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const s = catalog.strings;
  const step = catalog.steps[state.step];
  const total = catalog.steps.length;
  const isLast = state.step === total - 1;
  const canAdvance = stepComplete(step, state);
  const spec = useMemo(() => toSpec(catalog, state), [catalog, state]);
  const openGroup = state.openPicker ? catalog.groups[state.openPicker] : null;

  // Reloading the page drops you here even when she already exists, so an
  // untouched pass through the wizard must NOT re-run genesis and wipe her
  // history — it just continues to the conversation.
  const unchanged = onboarded && specsEqual(spec, existing);

  async function submit() {
    if (!spec) return;
    if (unchanged) {
      onSkip();
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      // Re-creating an existing companion needs reset=true or the API answers 409.
      await createCompanion(spec, onboarded);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : s.error);
      setSubmitting(false);
    }
  }

  function generateAvatar() {
    const style = state.draft.style ?? "realistic";
    const ethnicity = state.draft.ethnicity;
    if (!ethnicity) return;
    dispatch({
      type: "setAvatar",
      url: `/media/avatars/${style}/${ethnicity}_${state.draft.hair_color}.webp`,
    });
  }

  return (
    <div className="wizard">
      <header className="wizard-header">
        <button type="button" className="header-link" onClick={onBack}>
          <span className="chev">›</span>
          {s.preset_back}
        </button>
        {onLogout && (
          <button type="button" className="header-link" onClick={onLogout}>
            {s.logout}
          </button>
        )}
      </header>
      <h1>{s.title}</h1>
      <Stepper total={total} current={state.step} />

      <div className="wizard-body">
        {step.id !== "summary" && <h2 className="step-title">{step.he}</h2>}

        {step.id === "character" ? (
          <>
            <div className="picker-grid">
              {step.groups.map((gid) => (
                <PickerCard
                  key={gid}
                  group={catalog.groups[gid]}
                  value={(state.draft as Record<string, never>)[gid]}
                  notSet={s.not_set}
                  open={state.openPicker === gid}
                  onToggleOpen={() => dispatch({ type: "openPicker", group: gid })}
                />
              ))}
            </div>

            {openGroup && (
              <EmojiGrid
                group={openGroup}
                value={(state.draft as Record<string, never>)[openGroup.id]}
                onSelect={(option) =>
                  dispatch(
                    openGroup.multi
                      ? { type: "toggle", group: openGroup.id, option }
                      : { type: "select", group: openGroup.id, option },
                  )
                }
              />
            )}

            <div>
              <button
                type="button"
                className="details-toggle"
                onClick={() => dispatch({ type: "toggleDetails" })}
              >
                {s.more_details} {state.showDetails ? "▲" : "▼"}
              </button>
              {state.showDetails && (
                <div className="details-box">
                  <textarea
                    dir="auto"
                    maxLength={500}
                    placeholder={s.more_details_placeholder}
                    value={state.draft.extra_details ?? ""}
                    onChange={(e) => dispatch({ type: "setDetails", text: e.target.value })}
                  />
                </div>
              )}
            </div>
          </>
        ) : step.id === "summary" ? (
          <Summary
            catalog={catalog}
            state={state}
            onName={(name) => dispatch({ type: "setName", name })}
            onGenerate={generateAvatar}
          />
        ) : (
          <>
            {step.groups.map((gid) => (
              <TileGrid
                key={gid}
                group={catalog.groups[gid]}
                size={TILE_SIZE[gid] ?? "default"}
                showTitle={catalog.groups[gid].he !== step.he}
                value={(state.draft as Record<string, string>)[gid]}
                onSelect={(option) => dispatch({ type: "select", group: gid, option })}
              />
            ))}
            {step.age && (
              <AgeSlider
                title={catalog.age.he}
                min={catalog.age.min}
                max={catalog.age.max}
                value={state.draft.age ?? catalog.age.default}
                suffix={s.age_suffix}
                onChange={(age) => dispatch({ type: "setAge", age })}
              />
            )}
          </>
        )}

        {isLast && onboarded && !unchanged && (
          <p className="form-warning">⚠ {s.recreate_warning}</p>
        )}
        {error && <p className="form-error">{error}</p>}
      </div>

      <nav className="wizard-nav">
        <button
          type="button"
          className="btn btn-ghost"
          disabled={state.step === 0 || submitting}
          onClick={() => dispatch({ type: "prev" })}
          style={{ visibility: state.step === 0 ? "hidden" : "visible" }}
        >
          <span className="chev">‹</span>
          {s.previous}
        </button>

        {isLast ? (
          <button
            type="button"
            className="btn btn-primary"
            disabled={!spec || submitting}
            onClick={submit}
          >
            {submitting
              ? s.submitting
              : unchanged
                ? s.continue_to_chat
                : onboarded
                  ? s.recreate
                  : s.submit}
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-primary"
            disabled={!canAdvance}
            onClick={() => dispatch({ type: "next", total })}
          >
            {s.next}
            <span className="chev">›</span>
          </button>
        )}
      </nav>
    </div>
  );
}
