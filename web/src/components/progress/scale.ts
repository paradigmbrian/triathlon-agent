export function scaleLinear(d0: number, d1: number, r0: number, r1: number) {
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}

/** Round a maximum up to 1, 2, 5 or 10 times a power of ten; never 0. */
export function niceMax(max: number): number {
  if (!(max > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(max));
  const f = max / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

/** Five gridline values from 0 to niceMax(max). */
export function ticks(max: number): number[] {
  const m = niceMax(max);
  return [0, m / 4, m / 2, (3 * m) / 4, m];
}

/** SVG path strings for each unbroken run of values; a lone point becomes a zero-length line so a round cap draws a dot. */
export function segments(values: (number | null)[], x: (i: number) => number, y: (v: number) => number): string[] {
  const out: string[] = [];
  let run: string[] = [];
  const flush = () => {
    if (run.length === 1) out.push(`M${run[0]} L${run[0]}`);
    else if (run.length > 1) out.push(`M${run.join(" L")}`);
    run = [];
  };
  values.forEach((v, i) => {
    if (v == null) flush();
    else run.push(`${x(i)},${y(v)}`);
  });
  flush();
  return out;
}

export function axisDate(iso: string, withYear = false): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, withYear ? { month: "short", year: "2-digit" } : { month: "short", day: "numeric" });
}

/** About `n` evenly spaced axis labels for a list of ISO dates: [{i, text}]. */
export function axisLabels(dates: string[], n: number): { i: number; text: string }[] {
  if (dates.length === 0) return [];
  const withYear = dates.length > 120;
  const at = dates.length === 1 ? [0] : Array.from({ length: n }, (_, k) => Math.round((k * (dates.length - 1)) / (n - 1)));
  return [...new Set(at)].map((i) => ({ i, text: axisDate(dates[i], withYear) }));
}
