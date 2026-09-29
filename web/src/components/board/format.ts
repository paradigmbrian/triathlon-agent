import type { ConditionOut } from "../../api/queries";

/** Display digits per condition: formatting only; the thresholds live on the server. */
const DIGITS: Record<string, number> = { sleep_hours: 1, tsb: 1, acwr: 2, ramp: 1 };

export function conditionValue(c: ConditionOut): string {
  if (c.value == null) return "no data";
  const digits = DIGITS[c.key] ?? 0;
  const x = Number(c.value.toFixed(digits));
  const num = c.key === "ramp" ? `${x > 0 ? "+" : ""}${(x === 0 ? 0 : x).toFixed(digits)}` : x.toFixed(digits);
  if (!c.unit) return num;
  return c.unit.startsWith("/") ? `${num}${c.unit}` : `${num} ${c.unit}`;
}

export function baselineValue(c: ConditionOut): string {
  if (c.baseline == null) return "";
  return c.baseline.toFixed(DIGITS[c.key] ?? 0);
}
