import type { Group } from "../types";

interface Props {
  group: Group;
  value: string | string[] | undefined;
  onSelect: (optionId: string) => void;
}

/** Full-width option panel for a character picker. */
export default function EmojiGrid({ group, value, onSelect }: Props) {
  const selected = Array.isArray(value) ? value : value ? [value] : [];

  return (
    <div className="emoji-panel">
      {group.options.map((option) => (
        <button
          type="button"
          key={option.id}
          className={`emoji-option ${selected.includes(option.id) ? "selected" : ""}`}
          onClick={() => onSelect(option.id)}
          aria-pressed={selected.includes(option.id)}
        >
          <span className="glyph">{option.emoji}</span>
          <span>{option.he}</span>
        </button>
      ))}
    </div>
  );
}
