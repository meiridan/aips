import { useState } from "react";

import type { Group } from "../types";

interface Props {
  group: Group;
  value?: string;
  size?: "wide" | "default" | "short";
  /** Suppressed when the step heading above already says the same thing. */
  showTitle?: boolean;
  onSelect: (optionId: string) => void;
}

/** One image tile. Falls back to a gradient when the curated art is missing so
 *  the wizard is usable before the art library is filled in. */
function Tile({
  label,
  asset,
  color,
  selected,
  onClick,
}: {
  label: string;
  asset: string | null;
  color: string | null;
  selected: boolean;
  onClick: () => void;
}) {
  const [broken, setBroken] = useState(false);
  return (
    <button
      type="button"
      className={`tile ${selected ? "selected" : ""}`}
      onClick={onClick}
      aria-pressed={selected}
    >
      {asset && !broken ? (
        <img src={asset} alt="" loading="lazy" onError={() => setBroken(true)} />
      ) : (
        <div className="tile-fallback" style={color ? { background: color } : undefined} />
      )}
      <span className="tile-label">{label}</span>
      {selected && <span className="check">✓</span>}
    </button>
  );
}

export default function TileGrid({
  group,
  value,
  size = "default",
  showTitle = true,
  onSelect,
}: Props) {
  return (
    <section className="group">
      {showTitle && <h3 className="group-title">{group.he}</h3>}
      <div className={`tiles ${size === "default" ? "" : size}`}>
        {group.options.map((option) => (
          <Tile
            key={option.id}
            label={option.he}
            asset={option.asset}
            color={option.color}
            selected={value === option.id}
            onClick={() => onSelect(option.id)}
          />
        ))}
      </div>
    </section>
  );
}
