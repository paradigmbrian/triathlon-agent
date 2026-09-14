import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import { useSchema, type ReviewPayload, type Validated, type ValidationItem } from "../../api/queries";
import type { ReviewDecision } from "../chat/useTurnStream";
import ProposalCard from "./ProposalCard";
import SchemaForm from "./SchemaForm";
import YamlEditor from "./YamlEditor";
import { formPaths, type ProposalJson } from "./schemaUtils";

type Props = { payload: ReviewPayload; mode: "paused" | "held"; onDecide: (d: ReviewDecision) => Promise<void>; disabled?: boolean };

const btn = "rounded-md border border-line bg-surface-2 px-3 py-1.5 text-sm hover:bg-surface disabled:opacity-50";
const primary = "rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-on-fill disabled:opacity-50";

/** Errors keyed by their full loc path, e.g. `0.changes.1.new_date`. */
function errorMap(items: ValidationItem[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const e of items) {
    const key = e.loc.join(".");
    out[key] = out[key] ? `${out[key]}; ${e.msg}` : e.msg;
  }
  return out;
}

const lines = (items: ValidationItem[]) => items.map((e) => `${e.loc.join(".")}: ${e.msg}`);

function ErrorList({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="mt-1 space-y-0.5">
      {items.map((t, i) => (
        <li key={i} className="text-xs text-danger">
          {t}
        </li>
      ))}
    </ul>
  );
}

function GateBody({ payload, mode, onDecide, disabled }: Props) {
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState<"none" | "form" | "yaml">("none");
  const [drafts, setDrafts] = useState<ProposalJson[]>(payload.proposals);
  const [yaml, setYaml] = useState("");
  const [validated, setValidated] = useState<Validated | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const schema = useSchema();
  // `seq` identifies the latest validate request; a response for any other request is stale.
  const pending = useRef<{ timer?: number; seq: number }>({ seq: 0 });

  useEffect(() => {
    const p = pending.current;
    return () => window.clearTimeout(p.timer);
  }, []);

  /** Cancel an unfired validate and make any in-flight response stale. */
  const dropPending = () => {
    window.clearTimeout(pending.current.timer);
    pending.current.seq += 1;
  };

  const validate = (body: { proposals: unknown[] } | { yaml: string }) => {
    dropPending();
    const seq = pending.current.seq;
    pending.current.timer = window.setTimeout(async () => {
      try {
        const result = await api<Validated>("/api/coach/review/validate", { method: "POST", body: JSON.stringify(body) });
        if (seq === pending.current.seq) setValidated(result);
      } catch (e) {
        if (seq === pending.current.seq) setRefused(e instanceof Error ? e.message : String(e));
      }
    }, 300);
  };

  const switchTo = (next: "none" | "form" | "yaml") => {
    dropPending();
    setEditing(next);
    setValidated(null);
    setRefused(null);
  };

  const decide = async (d: ReviewDecision) => {
    try {
      await onDecide(d);
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        const body = e.body as { errors?: ValidationItem[]; detail?: string } | null;
        setValidated({ ok: false, proposals: [], errors: body?.errors ?? [] });
        setRefused(body?.detail ?? "edit rejected");
      }
      // anything else is already surfaced by the chat's error bubble
    }
  };

  const startYaml = async () => {
    dropPending();
    try {
      const { yaml: text } = await api<{ yaml: string }>("/api/coach/review/yaml");
      setYaml(text);
      switchTo("yaml");
    } catch (e) {
      setRefused(e instanceof Error ? e.message : String(e));
    }
  };

  const sendEdited = async () => {
    const proposals = editing === "yaml" ? validated?.proposals : drafts;
    if (editing === "yaml" && !validated?.ok) return;
    if (!proposals || proposals.length === 0) {
      setRefused("removing every proposal is not an edit; reject instead");
      return;
    }
    dropPending();
    setRefused(null);
    await decide({ action: "edit", proposals });
  };

  const items = useMemo(() => validated?.errors ?? [], [validated]);
  const errors = useMemo(() => errorMap(items), [items]);
  const perProposal = (i: number) =>
    Object.fromEntries(
      Object.entries(errors)
        .filter(([k]) => k.startsWith(`${i}.`))
        .map(([k, v]) => [k.slice(`${i}.`.length), v]),
    );
  // Form mode: errors the form has no field for, listed under their proposal (or under all forms).
  const unmatchedFor = (i: number, p: ProposalJson) => {
    const paths = schema.data ? formPaths(schema.data, p) : new Set<string>();
    return items
      .filter((e) => e.loc[0] === i && !paths.has(e.loc.slice(1).join(".")))
      .map((e) => (e.loc.length > 1 ? `${e.loc.slice(1).join(".")}: ${e.msg}` : e.msg));
  };
  const orphans = lines(items.filter((e) => typeof e.loc[0] !== "number" || e.loc[0] >= drafts.length));

  const setDraftsAndValidate = (next: ProposalJson[]) => {
    setDrafts(next);
    validate({ proposals: next });
  };

  return (
    <section aria-label="Review" className="rounded-lg border border-warn/60 border-l-4 border-l-warn bg-surface-2 p-4 shadow-sm">
      <p className="text-sm leading-relaxed font-medium">{payload.narration}</p>
      {mode === "held" && <p className="mt-1 text-xs text-warn">held from an earlier apply; ask the coach to re-propose it</p>}
      <div className="mt-3 space-y-2">
        {editing === "none" && payload.proposals.map((p) => <ProposalCard key={p.id} p={p} />)}
        {editing === "form" && schema.data && (
          <>
            {drafts.map((p, i) => (
              <div key={p.id}>
                <SchemaForm
                  schema={schema.data}
                  proposal={p}
                  errors={perProposal(i)}
                  canRemove={drafts.length > 1}
                  onRemove={() => setDraftsAndValidate(drafts.filter((_, j) => j !== i))}
                  onChange={(next) => setDraftsAndValidate(drafts.map((d, j) => (j === i ? next : d)))}
                />
                <ErrorList items={unmatchedFor(i, p)} />
              </div>
            ))}
            <ErrorList items={orphans} />
          </>
        )}
        {editing === "yaml" && (
          <YamlEditor
            value={yaml}
            onChange={(v) => {
              setYaml(v);
              setValidated(null); // Send stays disabled until this text validates
              validate({ yaml: v });
            }}
            errors={lines(items)}
          />
        )}
      </div>
      {refused && <p className="mt-2 text-xs text-danger">{refused}</p>}
      {mode === "paused" && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {editing === "none" ? (
            <>
              <input
                aria-label="note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="note (optional)"
                className="min-w-40 flex-1 rounded-md border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-ink-2"
              />
              <button type="button" disabled={disabled} onClick={() => void decide({ action: "approve" })} className={primary}>
                Approve
              </button>
              <button type="button" disabled={disabled} onClick={() => void decide({ action: "reject", note: note || null })} className={btn}>
                Reject
              </button>
              <button type="button" disabled={disabled} onClick={() => switchTo("form")} className={btn}>
                Edit
              </button>
            </>
          ) : (
            <>
              <button type="button" disabled={disabled || (editing === "yaml" && !validated?.ok)} onClick={() => void sendEdited()} className={primary}>
                Send edited
              </button>
              {editing === "form" ? (
                <button type="button" onClick={() => void startYaml()} className={btn}>
                  Edit as YAML
                </button>
              ) : (
                <button type="button" onClick={() => switchTo("form")} className={btn}>
                  Edit as form
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  switchTo("none");
                  setDrafts(payload.proposals);
                }}
                className={btn}
              >
                Cancel
              </button>
            </>
          )}
        </div>
      )}
    </section>
  );
}

/**
 * Keyed by the payload's content and mode: a new review (or a paused gate turning held) starts
 * fresh, while a refetch that returns the same proposals keeps any edit in progress.
 */
export default function Gate(props: Props) {
  const key = useMemo(() => `${props.mode}:${JSON.stringify(props.payload)}`, [props.mode, props.payload]);
  return <GateBody key={key} {...props} />;
}
