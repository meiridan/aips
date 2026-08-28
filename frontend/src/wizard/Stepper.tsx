interface Props {
  total: number;
  current: number;
}

/** Progress rail. Under dir="rtl" the flex row already runs right-to-left. */
export default function Stepper({ total, current }: Props) {
  const nodes = [];
  for (let i = 0; i < total; i++) {
    if (i > 0) {
      nodes.push(<div key={`bar-${i}`} className={`bar ${i <= current ? "done" : ""}`} />);
    }
    const cls = i < current ? "done" : i === current ? "current" : "";
    nodes.push(
      <div key={`dot-${i}`} className={`dot ${cls}`} aria-current={i === current}>
        {i < current ? "✓" : ""}
      </div>,
    );
  }
  return (
    <div className="stepper" role="progressbar" aria-valuenow={current + 1} aria-valuemax={total}>
      {nodes}
    </div>
  );
}
