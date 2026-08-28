import type { Group } from "../types";

interface Props {
  group: Group;
  value: string | string[] | undefined;
  notSet: string;
  open: boolean;
  onToggleOpen: () => void;
}

function labelFor(group: Group, value: string | string[] | undefined, notSet: string) {
  const ids = Array.isArray(value) ? value : value ? [value] : [];
  if (ids.length === 0) return notSet;
  return group.options
    .filter((o) => ids.includes(o.id))
    .map((o) => o.he)
    .join(", ");
}

function emojiFor(group: Group, value: string | string[] | undefined) {
  const ids = Array.isArray(value) ? value : value ? [value] : [];
  return group.options.find((o) => o.id === ids[0])?.emoji ?? null;
}

/** The "CHOOSE X / לא נבחר" summary card (comp screens 5-6). The option panel
 *  it opens is rendered full-width by the wizard, not inside this grid cell. */
export default function PickerCard({ group, value, notSet, open, onToggleOpen }: Props) {
  const filled = labelFor(group, value, notSet) !== notSet;
  const emoji = emojiFor(group, value);

  return (
    <button
      type="button"
      className={`picker-card ${open ? "open" : ""} ${filled ? "filled" : ""}`}
      onClick={onToggleOpen}
      aria-expanded={open}
    >
      {emoji && <span className="picker-emoji">{emoji}</span>}
      <span className="picker-text">
        <span className="picker-label">{group.he}</span>
        <span className="picker-value">{labelFor(group, value, notSet)}</span>
      </span>
      <span className="picker-pencil">{open ? "✕" : "✎"}</span>
    </button>
  );
}
