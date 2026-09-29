export const SPORTS = ["swim", "bike", "run", "strength", "other"] as const;
export type Sport = (typeof SPORTS)[number];

export const SPORT_LABEL: Record<Sport, string> = { swim: "Swim", bike: "Bike", run: "Run", strength: "Strength", other: "Other" };

export const sportKey = (s: string): Sport => ((SPORTS as readonly string[]).includes(s) ? (s as Sport) : "other");
export const sportColor = (s: Sport) => `var(--sport-${s})`;

/** Merge a record keyed by any sport label into the five the UI draws; unknown labels add into "other". */
export function fold<T>(rec: Record<string, T>, add: (a: T, b: T) => T): Partial<Record<Sport, T>> {
  const out: Partial<Record<Sport, T>> = {};
  for (const [k, v] of Object.entries(rec)) {
    const s = sportKey(k);
    out[s] = out[s] === undefined ? v : add(out[s] as T, v);
  }
  return out;
}
