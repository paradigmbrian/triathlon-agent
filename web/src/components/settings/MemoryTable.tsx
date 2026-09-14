import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiNoContent, ApiError } from "../../api/client";
import { keys, useMemory } from "../../api/queries";
import { day } from "../../lib/format";

export default function MemoryTable() {
  const qc = useQueryClient();
  const memory = useMemory();
  const forget = useMutation({
    mutationFn: (id: string) => apiNoContent(`/api/coach/memory/${id}`, { method: "DELETE" }),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.memory }),
  });
  const entries = memory.data?.entries ?? [];
  const active = new Set(memory.data?.active_ids ?? []);
  if (memory.isPending) return <p className="text-ink-2">loading…</p>;
  if (memory.isError) return <p className="text-danger">could not load memory: {memory.error instanceof Error ? memory.error.message : String(memory.error)}</p>;
  if (entries.length === 0) return <p className="text-ink-2">nothing remembered yet</p>;
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <thead className="text-left text-xs text-ink-2">
            <tr><th className="py-1">kind</th><th>text</th><th>created</th><th>until</th><th></th><th></th></tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id} className="border-t border-line">
                <td className="py-1.5 pr-2 align-top">{e.kind}</td>
                <td className="pr-2 break-words">{e.text}</td>
                <td className="pr-2 whitespace-nowrap text-ink-2">{day(e.created)}</td>
                <td className="pr-2 whitespace-nowrap text-ink-2">{e.until ? day(e.until) : "–"}</td>
                <td className="pr-2 text-xs">{active.has(e.id) ? <span className="text-accent">active</span> : <span className="text-ink-2">expired</span>}</td>
                <td><button type="button" disabled={forget.isPending} aria-label={`forget ${e.id}`} onClick={() => forget.mutate(e.id)} className="text-xs text-danger disabled:opacity-50">forget</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {forget.isError && <p className="mt-2 text-xs text-danger">forget failed: {forget.error instanceof ApiError ? forget.error.message : forget.error instanceof Error ? forget.error.message : String(forget.error)}</p>}
    </div>
  );
}
