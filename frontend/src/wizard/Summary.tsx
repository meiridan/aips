import { useState } from "react";

import type { Catalog, PersonaSpec } from "../types";
import type { WizardState } from "./wizardReducer";

interface Props {
  catalog: Catalog;
  state: WizardState;
  onName: (name: string) => void;
  onGenerate: () => void;
}

const APPEARANCE = [
  "ethnicity",
  "eye_color",
  "body_type",
  "breast_size",
  "hair_style",
  "hair_color",
  "butt_size",
  "clothing",
];
const CHARACTER = ["personality", "relationship", "occupation", "hobbies", "voice_style", "style"];

function valueLabel(catalog: Catalog, groupId: string, draft: Partial<PersonaSpec>) {
  const group = catalog.groups[groupId];
  const raw = (draft as Record<string, unknown>)[groupId];
  if (Array.isArray(raw)) {
    return (
      group.options
        .filter((o) => (raw as string[]).includes(o.id))
        .map((o) => o.he)
        .join(", ") || catalog.strings.not_set
    );
  }
  return group.options.find((o) => o.id === raw)?.he ?? catalog.strings.not_set;
}

/** Final screen: avatar, name, and a read-back of every choice (comp screen 7). */
export default function Summary({ catalog, state, onName, onGenerate }: Props) {
  const [tab, setTab] = useState<"appearance" | "character">("appearance");
  const s = catalog.strings;
  const groups = tab === "appearance" ? APPEARANCE : CHARACTER;

  return (
    <div className="summary">
      <div>
        <div className="avatar-box">
          {state.avatar ? (
            <img src={state.avatar} alt={state.draft.name ?? ""} />
          ) : (
            <div>
              <div style={{ fontSize: 34 }}>✨</div>
              <div style={{ marginBlockStart: 10, fontWeight: 700 }}>{s.no_image}</div>
              <div style={{ fontSize: 13 }}>{s.no_image_hint}</div>
            </div>
          )}
        </div>
        <button type="button" className="generate-btn" onClick={onGenerate}>
          ✨ {s.generate}
        </button>
      </div>

      <div>
        <input
          className="name-input"
          value={state.draft.name ?? ""}
          placeholder={s.name_placeholder}
          maxLength={40}
          dir="auto"
          onChange={(e) => onName(e.target.value)}
        />

        <div className="summary-tabs">
          <button
            type="button"
            className={tab === "appearance" ? "active" : ""}
            onClick={() => setTab("appearance")}
          >
            ✦ {s.tab_appearance}
          </button>
          <button
            type="button"
            className={tab === "character" ? "active" : ""}
            onClick={() => setTab("character")}
          >
            ⚙ {s.tab_character}
          </button>
        </div>

        <div className="summary-grid">
          {tab === "appearance" && (
            <div className="summary-cell">
              <span className="k">{catalog.age.he}</span>
              <span className="v">
                {catalog.strings.age_suffix} {state.draft.age}
              </span>
            </div>
          )}
          {groups.map((gid) => (
            <div className="summary-cell" key={gid}>
              <span className="k">{catalog.groups[gid].he}</span>
              <span className="v">{valueLabel(catalog, gid, state.draft)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
