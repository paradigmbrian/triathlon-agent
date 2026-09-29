import type { ProgressView } from "../../api/queries";

export type SportTotals = ProgressView["weeks"][number]["by_sport"][string];
export type Metric = "distance" | "duration" | "elevation" | "calories";

export const miles = (m: number) => m / 1609.344;
export const hoursOf = (sec: number) => sec / 3600;

export const METRICS: Record<Metric, { label: string; unit: string; digits: number; of: (t: SportTotals) => number }> = {
  distance: { label: "Distance", unit: "mi", digits: 1, of: (t) => miles(t.distance_m) },
  duration: { label: "Duration", unit: "h", digits: 1, of: (t) => hoursOf(t.duration_sec) },
  elevation: { label: "Elevation", unit: "ft", digits: 0, of: (t) => t.elevation_m * 3.28084 },
  calories: { label: "Calories", unit: "kcal", digits: 0, of: (t) => t.calories },
};

/** A signed figure for a change: "+1.5", "−4.0" (a real minus), "0.0", or a dash for no data. */
export function signed(v: number | null, digits = 1): string {
  if (v == null) return "–";
  const x = Number(v.toFixed(digits));
  if (x === 0) return (0).toFixed(digits);
  return `${x > 0 ? "+" : "−"}${Math.abs(x).toFixed(digits)}`;
}
