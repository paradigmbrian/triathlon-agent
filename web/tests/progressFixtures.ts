import type { ProgressView } from "../src/api/queries";

const totals = (o: Partial<{ duration_sec: number; distance_m: number; elevation_m: number; calories: number; tss: number }> = {}) => ({
  duration_sec: 0, distance_m: 0, elevation_m: 0, calories: 0, tss: 0, ...o,
});

/** Three weeks (the last partial), five PMC days with a gap, two sports plus one the UI does not know. */
export function progressFull(): ProgressView {
  return {
    range: "12m",
    start: "2026-08-31",
    end: "2026-09-16",
    as_of: "2026-09-16",
    pmc: [
      { date: "2026-09-12", ctl: 38, atl: 42, tsb: -4, tss: 60 },
      { date: "2026-09-13", ctl: 38.5, atl: 43, tsb: -4.5, tss: 0 },
      { date: "2026-09-14", ctl: null, atl: null, tsb: null, tss: null },
      { date: "2026-09-15", ctl: 39.5, atl: 44, tsb: -4.5, tss: 80 },
      { date: "2026-09-16", ctl: 40, atl: 45, tsb: -5, tss: 50 },
    ],
    ramp: [
      { days: 7, delta: 1.5, series: [38.5, null, 39, 39.5, 39.8, 39.9, 40, 40] },
      { days: 28, delta: null, series: [] },
      { days: 90, delta: -4, series: [44, 43, 40] },
      { days: 365, delta: -41, series: [81, 60, 40] },
    ],
    weeks: [
      { week_start: "2026-08-31", partial: false, by_sport: { bike: totals({ duration_sec: 7200, distance_m: 48280, elevation_m: 300, calories: 1200, tss: 90 }), run: totals({ duration_sec: 3600, distance_m: 10000, elevation_m: 50, calories: 700, tss: 60 }) }, longest: { duration_sec: 7200, distance_m: 48280 } },
      { week_start: "2026-09-07", partial: false, by_sport: { bike: totals({ duration_sec: 3600, distance_m: 24140, elevation_m: 100, calories: 600, tss: 45 }), brick: totals({ duration_sec: 1800, distance_m: 5000, elevation_m: 10, calories: 300, tss: 30 }) }, longest: { duration_sec: 3600, distance_m: 24140 } },
      { week_start: "2026-09-14", partial: true, by_sport: { run: totals({ duration_sec: 1800, distance_m: 5000, elevation_m: 20, calories: 350, tss: 30 }) }, longest: { duration_sec: 1800, distance_m: 5000 } },
    ],
    share: {
      completed: { duration_sec: { bike: 10800, run: 5400, brick: 1800 }, distance_m: { bike: 72420, run: 15000 } },
      planned: { duration_sec: { bike: 12000, run: 7200 }, distance_m: { bike: 80000, run: 20000 } },
    },
  };
}

export function progressEmpty(): ProgressView {
  return {
    range: "12m", start: "2026-08-31", end: "2026-09-16", as_of: null,
    pmc: [{ date: "2026-09-16", ctl: null, atl: null, tsb: null, tss: null }],
    ramp: [7, 28, 90, 365].map((days) => ({ days, delta: null, series: [] })),
    weeks: [{ week_start: "2026-09-14", partial: true, by_sport: {}, longest: { duration_sec: 0, distance_m: 0 } }],
    share: { completed: { duration_sec: {}, distance_m: {} }, planned: { duration_sec: {}, distance_m: {} } },
  };
}
