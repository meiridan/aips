interface Props {
  title: string;
  min: number;
  max: number;
  value: number;
  suffix: string;
  onChange: (age: number) => void;
}

export default function AgeSlider({ title, min, max, value, suffix, onChange }: Props) {
  return (
    <section className="group">
      <h3 className="group-title">{title}</h3>
      <div className="age">
        <div className="age-pill">
          {suffix} {value}
        </div>
        <div className="age-row">
          <span>{min}</span>
          <input
            type="range"
            min={min}
            max={max}
            value={value}
            aria-label={title}
            onChange={(e) => onChange(Number(e.target.value))}
          />
          <span>{max}+</span>
        </div>
      </div>
    </section>
  );
}
