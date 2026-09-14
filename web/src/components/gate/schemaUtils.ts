import type { ProposalJson, SchemaOut } from "../../api/queries";
import { day } from "../../lib/format";

export type { ProposalJson } from "../../api/queries";

export type JsonSchema = Record<string, unknown>;
export type FieldKind = "string" | "date" | "number" | "boolean" | "enum" | "object" | "dict" | "json";
export type Field = { name: string; kind: FieldKind; enum?: string[]; required: boolean; nested?: Field[] };

function resolve(s: JsonSchema, root: JsonSchema): JsonSchema {
  const ref = s.$ref as string | undefined;
  if (ref?.startsWith("#/$defs/")) {
    const defs = (root.$defs ?? {}) as Record<string, JsonSchema>;
    return defs[ref.slice("#/$defs/".length)] ?? {};
  }
  const anyOf = s.anyOf as JsonSchema[] | undefined;
  if (anyOf) {
    const nonNull = anyOf.filter((x) => x.type !== "null");
    if (nonNull.length === 1) return resolve(nonNull[0], root);
  }
  return s;
}

function kindOf(s: JsonSchema): FieldKind {
  if (Array.isArray(s.enum)) return "enum";
  const t = s.type;
  if (t === "string") return s.format === "date" ? "date" : "string";
  if (t === "integer" || t === "number") return "number";
  if (t === "boolean") return "boolean";
  if (t === "object") return s.properties ? "object" : "dict";
  return "json";
}

export function fieldsOf(schema: JsonSchema, root: JsonSchema): Field[] {
  const props = (schema.properties ?? {}) as Record<string, JsonSchema>;
  const required = new Set((schema.required ?? []) as string[]);
  return Object.entries(props).map(([name, raw]) => {
    const s = resolve(raw, root);
    const kind = kindOf(s);
    const nullable = Array.isArray(raw.anyOf) && (raw.anyOf as JsonSchema[]).some((x) => x.type === "null");
    return {
      name,
      kind,
      enum: kind === "enum" ? (s.enum as string[]) : undefined,
      required: required.has(name) && !nullable,
      nested: kind === "object" ? fieldsOf(s, root) : undefined,
    };
  });
}

export function changeSchema(all: SchemaOut, domain: "planning" | "nutrition"): JsonSchema {
  return domain === "planning" ? all.planning_change : all.nutrition_change;
}

/** Error paths SchemaForm renders for a proposal (relative to the proposal, e.g. `changes.0.new_date`). */
export function formPaths(all: SchemaOut, proposal: ProposalJson): Set<string> {
  const cs = changeSchema(all, proposal.domain);
  const fields = fieldsOf(cs, cs);
  const out = new Set<string>(["summary"]);
  if (proposal.domain === "nutrition") out.add("overrides");
  const walk = (fs: Field[], value: Record<string, unknown>, prefix: string) => {
    for (const f of fs) {
      const path = `${prefix}.${f.name}`;
      out.add(path);
      const v = value[f.name];
      if (f.kind === "object" && f.nested && v && typeof v === "object") walk(f.nested, v as Record<string, unknown>, path);
    }
  };
  proposal.changes.forEach((c, i) => walk(fields, c, `changes.${i}`));
  return out;
}

export function describeChange(domain: string, c: Record<string, unknown>): string {
  const op = String(c.op);
  if (domain === "planning") {
    const w = (c.workout ?? null) as Record<string, unknown> | null;
    const session = w ? `${String(w.sport)} ${String(w.duration_minutes)} min${w.description ? `, ${String(w.description)}` : ""}` : "";
    if (op === "move") return `move ${String(c.tp_workout_id)} to ${day(c.new_date as string)}`;
    if (op === "delete") return `delete ${String(c.tp_workout_id)}`;
    if (op === "create") return `create ${day(c.workout_date as string)}: ${session}`;
    if (op === "update") return `update ${String(c.tp_workout_id)}${session ? `: ${session}` : ""}`;
    return op;
  }
  const payload = (c.payload ?? {}) as Record<string, unknown>;
  const pairs = Object.entries(payload)
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(", ");
  return `${op} ${day(c.day as string)}${pairs ? `: ${pairs}` : ""}`;
}
