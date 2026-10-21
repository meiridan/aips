import { useMemo, useState } from "react";

import type { Catalog, Preset, User } from "../types";
import PresetCard from "./PresetCard";

interface Props {
  catalog: Catalog;
  /** Who is signed in, for the header avatar. Null while dev-login is on. */
  user: User | null;
  onOpen: (preset: Preset) => void;
  /** Leave the gallery for the six-step build-your-own wizard. */
  onCustom: () => void;
  /** Omitted in single-user mode: nothing to log out of, so no button. */
  onLogout?: () => void;
}

/** Which single-choice group each chip row filters on: `spec[group] === option`. */
type Selected = Record<string, string>;

function matches(preset: Preset, query: string, selected: Selected): boolean {
  for (const [group, option] of Object.entries(selected)) {
    if (preset.spec[group] !== option) return false;
  }
  if (!query) return true;
  const needle = query.trim().toLowerCase();
  return [preset.name, preset.tagline, preset.bio]
    .join(" ")
    .toLowerCase()
    .includes(needle);
}

/** The app's opening screen: nine ready-made companions, plus an escape hatch
 *  to the full creation wizard.
 *
 *  Search and filtering are client-side on purpose — the whole catalog is nine
 *  characters that already arrived with `GET /api/catalog`, so a round trip per
 *  keystroke would buy nothing. The filterable groups come from the server
 *  (`preset_filters`) rather than being listed here, the same rule as the
 *  wizard's steps. */
export default function PresetGallery({ catalog, user, onOpen, onCustom, onLogout }: Props) {
  const s = catalog.strings;
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Selected>({});
  const [menuOpen, setMenuOpen] = useState(false);

  const filterGroups = (catalog.preset_filters ?? []).filter((gid) => catalog.groups[gid]);
  // Only offer options at least one character actually has — a chip that can
  // only ever return an empty grid is noise.
  const available = useMemo(() => {
    const seen: Record<string, Set<string>> = {};
    for (const gid of filterGroups) {
      seen[gid] = new Set(
        catalog.presets
          .map((p) => p.spec[gid])
          .filter((v): v is string => typeof v === "string"),
      );
    }
    return seen;
  }, [catalog.presets, filterGroups.join(",")]);

  const shown = catalog.presets.filter((p) => matches(p, query, selected));
  const filtered = query.trim() !== "" || Object.keys(selected).length > 0;

  function toggle(group: string, option: string) {
    setSelected((current) => {
      const next = { ...current };
      if (next[group] === option) delete next[group];
      else next[group] = option;
      return next;
    });
  }

  function clear() {
    setSelected({});
    setQuery("");
  }

  return (
    <div className="presets">
      <header className="presets-header">
        <h1 className="presets-title">{s.presets_title}</h1>

        <div className="presets-actions">
          <button
            type="button"
            className="icon-btn"
            aria-label={searching ? s.preset_search_close : s.preset_search}
            aria-pressed={searching}
            onClick={() => {
              // Closing the field also drops the query, so a hidden search box
              // can never keep characters out of the grid.
              if (searching) setQuery("");
              setSearching(!searching);
            }}
          >
            🔍
          </button>

          {/* The avatar menu holds nothing but the account: no login flow, no
              menu, rather than a button that opens an empty box. */}
          {onLogout && (
            <>
              <button
                type="button"
                className="avatar-btn"
                aria-label={user?.name ?? s.logout}
                aria-expanded={menuOpen}
                onClick={() => setMenuOpen(!menuOpen)}
              >
                {(user?.name ?? "").trim().slice(0, 1) || "🙂"}
              </button>

              {menuOpen && (
                <div className="header-menu">
                  {user?.email && <span className="header-menu-email">{user.email}</span>}
                  <button type="button" className="header-link" onClick={onLogout}>
                    {s.logout}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </header>

      {searching && (
        <input
          className="preset-search"
          type="search"
          autoFocus
          value={query}
          placeholder={s.preset_search_placeholder}
          aria-label={s.preset_search}
          onChange={(e) => setQuery(e.target.value)}
        />
      )}

      {filterGroups.length > 0 && (
        <div className="preset-filters">
          {filterGroups.map((gid) => {
            const group = catalog.groups[gid];
            return (
              <div key={gid} className="preset-filter-row">
                <span className="preset-filter-label">{group.he}</span>
                {group.options
                  .filter((o) => available[gid]?.has(o.id))
                  .map((o) => (
                    <button
                      key={o.id}
                      type="button"
                      className={`filter-chip${selected[gid] === o.id ? " on" : ""}`}
                      aria-pressed={selected[gid] === o.id}
                      onClick={() => toggle(gid, o.id)}
                    >
                      {o.he}
                    </button>
                  ))}
              </div>
            );
          })}
          {filtered && (
            <button type="button" className="header-link" onClick={clear}>
              {s.preset_filter_clear}
            </button>
          )}
        </div>
      )}

      <div className="preset-grid">
        {shown.map((preset) => (
          <PresetCard key={preset.id} preset={preset} strings={s} onOpen={() => onOpen(preset)} />
        ))}

        {/* The wizard tile is a way out of the gallery, not a search result —
            hide it while a filter is narrowing the grid. */}
        {!filtered && (
          <button type="button" className="preset-card custom" onClick={onCustom}>
            <span className="preset-custom-mark">✨</span>
            <span className="preset-caption">
              <span className="preset-name">{s.preset_custom}</span>
              <span className="preset-tagline">{s.preset_custom_hint}</span>
            </span>
          </button>
        )}
      </div>

      {shown.length === 0 && <p className="center-note">{s.preset_no_results}</p>}
    </div>
  );
}
