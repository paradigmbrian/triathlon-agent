import { axisLabels, niceMax, scaleLinear, segments, ticks } from "../src/components/progress/scale";
import { METRICS, signed } from "../src/components/progress/units";
import { fold, sportKey } from "../src/components/progress/sports";

test("scaleLinear maps the domain to the range and survives a flat domain", () => {
  const s = scaleLinear(0, 10, 100, 0);
  expect([s(0), s(5), s(10)]).toEqual([100, 50, 0]);
  expect(Number.isFinite(scaleLinear(5, 5, 0, 10)(5))).toBe(true);
});

test("niceMax rounds up to 1, 2, 5 or 10 times a power of ten and never returns 0", () => {
  expect([niceMax(0), niceMax(0.3), niceMax(7), niceMax(43), niceMax(101)]).toEqual([1, 0.5, 10, 50, 200]);
  expect(ticks(43)).toEqual([0, 12.5, 25, 37.5, 50]);
});

test("segments breaks the line at a gap and draws a lone point as a dot", () => {
  const out = segments([1, 2, null, 3, null, 4, 5], (i) => i * 10, (v) => v);
  expect(out).toEqual(["M0,1 L10,2", "M30,3 L30,3", "M50,4 L60,5"]);
  expect(segments([null, null], (i) => i, (v) => v)).toEqual([]);
});

test("axisLabels picks evenly spaced dates, one for a single date, none for none", () => {
  expect(axisLabels(["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26", "2026-02-02"], 3).map((l) => l.i)).toEqual([0, 2, 4]);
  expect(axisLabels(["2026-01-05"], 5).map((l) => l.i)).toEqual([0]);
  expect(axisLabels([], 5)).toEqual([]);
});

test("metrics convert to miles, feet and hours; signed shows a plus and a real minus", () => {
  const t = { duration_sec: 7200, distance_m: 1609.344, elevation_m: 100, calories: 500, tss: 0 };
  expect(METRICS.distance.of(t)).toBeCloseTo(1);
  expect(METRICS.duration.of(t)).toBe(2);
  expect(METRICS.elevation.of(t)).toBeCloseTo(328.084);
  expect(signed(1.5)).toBe("+1.5");
  expect(signed(-4)).toBe("−4.0");
  expect(signed(0)).toBe("0.0");
  expect(signed(null)).toBe("–");
});

test("unknown sports fold into other and their totals add", () => {
  expect(sportKey("brick")).toBe("other");
  expect(sportKey("bike")).toBe("bike");
  expect(fold({ bike: 1, brick: 2, walk: 4 }, (a, b) => a + b)).toEqual({ bike: 1, other: 6 });
});

test("long ranges label months with a four-digit year so they never read as a day", () => {
  const dates = Array.from({ length: 130 }, (_, i) => new Date(Date.UTC(2025, 8, 1 + i)).toISOString().slice(0, 10));
  const labels = axisLabels(dates, 5).map((l) => l.text);
  expect(labels.every((t) => /\b20\d\d\b/.test(t))).toBe(true);
});
