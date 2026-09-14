export const hours = (h: number | null | undefined) => (h == null ? "–" : `${h.toFixed(1)} h`);
export const secsAsHours = (s: number | null | undefined) => (s == null ? "–" : `${(s / 3600).toFixed(1)} h`);
export const n = (v: number | null | undefined, digits = 0) => (v == null ? "–" : v.toFixed(digits));
export const kcal = (v: number | null | undefined) => (v == null ? "–" : `${v.toLocaleString()} kcal`);
export const day = (iso: string | null | undefined) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }) : "–";
export const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "never";
