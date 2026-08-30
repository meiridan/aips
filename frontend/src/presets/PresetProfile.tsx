import { useState } from "react";

import { createCompanion } from "../api";
import type { Catalog, PersonaSpec, Preset } from "../types";
import { useVoicePreview } from "./useVoicePreview";

interface Props {
  catalog: Catalog;
  preset: Preset;
  /** She already exists — starting over has to pass reset=true and warn first. */
  onboarded: boolean;
  onBack: () => void;
  onStarted: () => void;
}

/** Groups worth surfacing on the profile, in reading order. Appearance is
 *  already visible in the photos, so this is who she is, not what she looks
 *  like. */
const HIGHLIGHTS = ["personality", "relationship", "occupation", "voice_style", "clothing"];

/** One contextual shot. A missing file collapses the slide rather than showing
 *  a broken image, so the strip shrinks gracefully toward an empty carousel. */
function Shot({ src }: { src: string }) {
  const [broken, setBroken] = useState(false);
  if (broken) return null;
  return <img src={src} alt="" loading="lazy" onError={() => setBroken(true)} />;
}

export default function PresetProfile({
  catalog,
  preset,
  onboarded,
  onBack,
  onStarted,
}: Props) {
  const s = catalog.strings;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const voice = useVoicePreview(preset);

  const hobbies = (preset.spec.hobbies as string[] | undefined) ?? [];

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const spec = {
        ...(preset.spec as unknown as PersonaSpec),
        name: preset.name,
        preset: preset.id,
      };
      // Re-creating over an existing companion needs reset=true or the API
      // answers 409 — the same contract Wizard.submit() works to.
      await createCompanion(spec, onboarded);
      onStarted();
    } catch (err) {
      setError(err instanceof Error ? err.message : s.error);
      setBusy(false);
    }
  }

  function label(groupId: string): string | null {
    const value = preset.spec[groupId];
    if (typeof value !== "string") return null;
    return catalog.groups[groupId]?.options.find((o) => o.id === value)?.he ?? null;
  }

  return (
    <div className="preset-profile">
      <header className="presets-header">
        <button type="button" className="header-link" onClick={onBack}>
          <span className="chev">›</span>
          {s.preset_back}
        </button>
      </header>

      <div className="preset-carousel">
        {[preset.portrait, ...preset.gallery].map((src) => (
          <Shot key={src} src={src} />
        ))}
      </div>

      <h1 className="preset-profile-name">{preset.name}</h1>
      <p className="preset-profile-tagline">{preset.tagline}</p>

      <div className="preset-voice">
        <button
          type="button"
          className="btn btn-ghost"
          onClick={voice.state === "playing" ? voice.stop : voice.play}
          disabled={voice.state === "unsupported"}
        >
          {voice.state === "playing" ? `⏹ ${s.preset_voice_stop}` : `🔊 ${s.preset_voice}`}
        </button>
        {voice.state === "unsupported" && (
          <span className="preset-voice-note">{s.preset_voice_unavailable}</span>
        )}
      </div>

      <section className="preset-section">
        <h2>{s.preset_about}</h2>
        <p className="preset-bio">{preset.bio}</p>
      </section>

      <section className="preset-section">
        <h2>{s.preset_details}</h2>
        <dl className="preset-facts">
          <div>
            <dt>{catalog.age.he}</dt>
            <dd>{String(preset.spec.age ?? "")}</dd>
          </div>
          {HIGHLIGHTS.map((gid) => {
            const value = label(gid);
            return value ? (
              <div key={gid}>
                <dt>{catalog.groups[gid].he}</dt>
                <dd>{value}</dd>
              </div>
            ) : null;
          })}
        </dl>
        {hobbies.length > 0 && (
          <div className="preset-chips">
            {hobbies.map((h) => {
              const opt = catalog.groups.hobbies.options.find((o) => o.id === h);
              return opt ? (
                <span key={h} className="preset-chip">
                  {opt.emoji} {opt.he}
                </span>
              ) : null;
            })}
          </div>
        )}
      </section>

      {onboarded && <p className="form-warning">⚠ {s.recreate_warning}</p>}
      {error && <p className="form-error">{error}</p>}

      <div className="preset-cta">
        <button type="button" className="btn btn-primary" onClick={start} disabled={busy}>
          {busy ? s.preset_creating : s.preset_start}
        </button>
      </div>
    </div>
  );
}
