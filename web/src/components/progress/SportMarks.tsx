import { SPORT_LABEL, sportColor, type Sport } from "./sports";

/** A shape per sport (circle, square, triangle, diamond, ring) so the legend never relies on colour alone. */
export function Marker({ sport, size = 12 }: { sport: Sport; size?: number }) {
  const c = sportColor(sport);
  const h = size / 2;
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
      {sport === "swim" && <circle cx={h} cy={h} r={h - 1} fill={c} />}
      {sport === "bike" && <rect x={1} y={1} width={size - 2} height={size - 2} fill={c} />}
      {sport === "run" && <polygon points={`${h},1 ${size - 1},${size - 1} 1,${size - 1}`} fill={c} />}
      {sport === "strength" && <polygon points={`${h},1 ${size - 1},${h} ${h},${size - 1} 1,${h}`} fill={c} />}
      {sport === "other" && <circle cx={h} cy={h} r={h - 1.5} fill="none" stroke={c} strokeWidth={2} />}
    </svg>
  );
}

export function Legend({ sports }: { sports: readonly Sport[] }) {
  return (
    <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
      {sports.map((s) => (
        <li key={s} className="inline-flex items-center gap-1.5">
          <Marker sport={s} />
          {SPORT_LABEL[s]}
        </li>
      ))}
    </ul>
  );
}
