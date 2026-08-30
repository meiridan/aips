interface Props {
  /** Announced to screen readers, e.g. "מאיה מקלידה…". */
  label: string;
}

/** The three-dot bubble shown while a reply is being generated.
 *
 *  `role="status"` rather than an alert: it is a progress hint, so it should be
 *  announced without interrupting whatever the reader is on. The dots are spans
 *  because the animation is per-dot and staggered (see .typing-dot).
 */
export default function TypingIndicator({ label }: Props) {
  return (
    <div className="bubble typing" role="status" aria-label={label}>
      <span className="typing-dot" />
      <span className="typing-dot" />
      <span className="typing-dot" />
    </div>
  );
}
