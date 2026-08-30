import { useState } from "react";

import type { Preset } from "../types";

interface Props {
  preset: Preset;
  strings: Record<string, string>;
  onOpen: () => void;
}

const BADGE_STRING: Record<string, string> = {
  new: "badge_new",
  trending: "badge_trending",
  online: "badge_online",
};

/** One character tile. Falls back to a gradient when the curated portrait is
 *  missing, the same way the wizard's tiles do — the gallery has to be usable
 *  before the art library is filled in. */
export default function PresetCard({ preset, strings, onOpen }: Props) {
  const [broken, setBroken] = useState(false);
  const badge = preset.badge ? strings[BADGE_STRING[preset.badge]] : null;

  return (
    <button type="button" className="preset-card" onClick={onOpen}>
      {broken ? (
        <div className="preset-fallback">
          <span>{preset.name.slice(0, 1)}</span>
        </div>
      ) : (
        <img src={preset.portrait} alt="" loading="lazy" onError={() => setBroken(true)} />
      )}

      {badge && <span className={`preset-badge ${preset.badge}`}>{badge}</span>}

      <span className="preset-caption">
        <span className="preset-name">{preset.name}</span>
        <span className="preset-tagline">{preset.tagline}</span>
      </span>
    </button>
  );
}
