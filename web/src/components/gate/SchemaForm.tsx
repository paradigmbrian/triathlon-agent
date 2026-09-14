import type { ReactNode } from "react";
import type { SchemaOut } from "../../api/queries";
import { changeSchema, fieldsOf, type Field, type ProposalJson } from "./schemaUtils";

type Errors = Record<string, string>;
type Obj = Record<string, unknown>;

function Err({ path, errors }: { path: string; errors: Errors }) {
  return errors[path] ? <p className="text-xs text-danger">{errors[path]}</p> : null;
}

function parse(v: string): unknown {
  try {
    return JSON.parse(v);
  } catch {
    return v;
  }
}

const shown = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

// Rows are keyed by their (unique) key name and commit on blur, so typing never remounts an input.
function KeyValues({ id, value, onChange }: { id: string; value: Obj; onChange: (v: Obj) => void }) {
  const entries = Object.entries(value);
  const set = (i: number, k: string, v: unknown) => onChange(Object.fromEntries(entries.map(([ek, ev], j) => (j === i ? [k, v] : [ek, ev]))));
  return (
    <div className="space-y-1" data-testid={id}>
      {entries.map(([k, v], i) => (
        <div key={k} className="flex gap-1">
          <input
            aria-label={`${id} key ${i + 1}`}
            defaultValue={k}
            onBlur={(e) => e.target.value !== k && set(i, e.target.value, v)}
            className="w-1/3 rounded border border-line bg-surface px-2 py-1 text-xs"
          />
          <input
            aria-label={`${id} value ${i + 1}`}
            defaultValue={shown(v)}
            onBlur={(e) => e.target.value !== shown(v) && set(i, k, parse(e.target.value))}
            className="flex-1 rounded border border-line bg-surface px-2 py-1 text-xs"
          />
          <button
            type="button"
            aria-label={`remove ${id} ${k}`}
            onClick={() => onChange(Object.fromEntries(entries.filter((_, j) => j !== i)))}
            className="text-xs text-ink-2"
          >
            ×
          </button>
        </div>
      ))}
      <button type="button" onClick={() => onChange({ ...value, "": "" })} className="text-xs text-accent">
        + add key
      </button>
    </div>
  );
}

type FieldProps = { field: Field; value: unknown; path: string; errors: Errors; onChange: (v: unknown) => void };

function FieldInput({ field, value, path, errors, onChange }: FieldProps) {
  const cls = "w-full rounded border border-line bg-surface px-2 py-1 text-sm";
  let input: ReactNode;
  let control = true;
  switch (field.kind) {
    case "enum":
      input = (
        <select id={path} value={String(value ?? "")} onChange={(e) => onChange(e.target.value || (field.required ? "" : null))} className={cls}>
          {!field.required && <option value="">–</option>}
          {(field.enum ?? []).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      );
      break;
    case "date":
      input = <input id={path} type="date" value={String(value ?? "")} onChange={(e) => onChange(e.target.value || null)} className={cls} />;
      break;
    case "number":
      input = (
        <input
          id={path}
          type="number"
          value={value == null ? "" : String(value)}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
          className={cls}
        />
      );
      break;
    case "boolean":
      input = <input id={path} type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />;
      break;
    case "dict":
      control = false;
      input = <KeyValues id={path} value={(value ?? {}) as Obj} onChange={onChange} />;
      break;
    case "object": {
      control = false;
      const obj = (value ?? null) as Obj | null;
      input = obj ? (
        <div className="ml-3 border-l border-line pl-3">
          {(field.nested ?? []).map((f) => (
            <FieldInput key={f.name} field={f} value={obj[f.name]} path={`${path}.${f.name}`} errors={errors} onChange={(v) => onChange({ ...obj, [f.name]: v })} />
          ))}
        </div>
      ) : (
        <span className="text-xs text-ink-2">none</span>
      );
      break;
    }
    case "json":
      input = (
        <input
          id={path}
          defaultValue={JSON.stringify(value ?? null)}
          onBlur={(e) => {
            try {
              onChange(JSON.parse(e.target.value));
            } catch {
              // not JSON yet: keep the last good value
            }
          }}
          className={`${cls} font-mono text-xs`}
        />
      );
      break;
    default:
      input = <input id={path} value={String(value ?? "")} onChange={(e) => onChange(e.target.value || (field.required ? "" : null))} className={cls} />;
  }
  return (
    <div className="mb-2">
      <div className="text-xs text-ink-2">
        {control ? <label htmlFor={path}>{field.name}</label> : <span>{field.name}</span>}
        {!field.required && <span> (optional)</span>}
      </div>
      {input}
      <Err path={path} errors={errors} />
    </div>
  );
}

type Props = { schema: SchemaOut; proposal: ProposalJson; errors: Errors; onChange: (p: ProposalJson) => void; onRemove: () => void; canRemove: boolean };

export default function SchemaForm({ schema, proposal, errors, onChange, onRemove, canRemove }: Props) {
  const domain = proposal.domain;
  const cs = changeSchema(schema, domain);
  const fields = fieldsOf(cs, cs);
  const changes = proposal.changes;
  const setChange = (i: number, next: Obj) => onChange({ ...proposal, changes: changes.map((c, j) => (j === i ? next : c)) });
  return (
    <div className="rounded-md border border-line bg-surface p-3">
      <div className="flex items-center gap-2 text-sm">
        <span className="font-mono">{proposal.id}</span>
        <span className={domain === "planning" ? "text-planning" : "text-nutrition"}>{domain}</span>
        {canRemove && (
          <button type="button" onClick={onRemove} aria-label="remove proposal" className="ml-auto text-xs text-danger">
            remove proposal
          </button>
        )}
      </div>
      <div className="mt-2">
        <label htmlFor={`${proposal.id}-summary`} className="block text-xs text-ink-2">
          summary
        </label>
        <input
          id={`${proposal.id}-summary`}
          aria-label="summary"
          value={proposal.summary}
          onChange={(e) => onChange({ ...proposal, summary: e.target.value })}
          className="w-full rounded border border-line bg-surface-2 px-2 py-1 text-sm"
        />
        <Err path="summary" errors={errors} />
      </div>
      {proposal.question && <p className="mt-2 text-sm">{proposal.question}</p>}
      {changes.map((c, i) => (
        <fieldset key={i} className="mt-3 rounded border border-line p-2">
          <legend className="px-1 text-xs text-ink-2">change {i + 1}</legend>
          {fields.map((f) => (
            <FieldInput key={f.name} field={f} value={c[f.name]} path={`changes.${i}.${f.name}`} errors={errors} onChange={(v) => setChange(i, { ...c, [f.name]: v })} />
          ))}
          <button
            type="button"
            aria-label={`remove change ${i + 1}`}
            onClick={() => onChange({ ...proposal, changes: changes.filter((_, j) => j !== i) })}
            className="text-xs text-danger"
          >
            remove change
          </button>
        </fieldset>
      ))}
      {domain === "nutrition" && (
        <div className="mt-3">
          <span className="block text-xs text-ink-2">overrides</span>
          <KeyValues id="overrides" value={proposal.overrides ?? {}} onChange={(v) => onChange({ ...proposal, overrides: Object.keys(v).length ? v : null })} />
          <Err path="overrides" errors={errors} />
        </div>
      )}
    </div>
  );
}
