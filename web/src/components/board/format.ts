import type { ConditionOut } from "../../api/queries";

/** Display digits per condition: formatting only; the thresholds live on the server. */
const DIGITS: Record<string, number> = { sleep_hours: 1, tsb: 1, acwr: 2, ramp: 1 };

/** The figure and its unit apart, so the board can set the unit small. `unit` carries its own leading space. */
export function conditionParts(c: ConditionOut): { num: string; unit: string } | null {
  if (c.value == null) return null;
  const digits = DIGITS[c.key] ?? 0;
  const x = Number(c.value.toFixed(digits));
  const num = c.key === "ramp" ? `${x > 0 ? "+" : ""}${(x === 0 ? 0 : x).toFixed(digits)}` : x.toFixed(digits);
  if (!c.unit) return { num, unit: "" };
  return { num, unit: c.unit.startsWith("/") ? c.unit : ` ${c.unit}` };
}

export function conditionValue(c: ConditionOut): string {
  const p = conditionParts(c);
  return p ? `${p.num}${p.unit}` : "no data";
}

export function baselineValue(c: ConditionOut): string {
  if (c.baseline == null) return "";
  return c.baseline.toFixed(DIGITS[c.key] ?? 0);
}
