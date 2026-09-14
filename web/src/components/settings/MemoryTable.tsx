import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiNoContent } from "../../api/client";
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
  if (entries.length === 0) return <p className="text-ink-2">nothing remembered yet</p>;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs text-ink-2">
        <tr><th className="py-1">kind</th><th>text</th><th>created</th><th>until</th><th></th><th></th></tr>
      </thead>
      <tbody>
        {entries.map((e) => (
          <tr key={e.id} className="border-t border-line">
            <td className="py-1 pr-2">{e.kind}</td>
            <td className="pr-2">{e.text}</td>
            <td className="pr-2 text-ink-2">{day(e.created)}</td>
            <td className="pr-2 text-ink-2">{e.until ? day(e.until) : "–"}</td>
            <td className="pr-2 text-xs">{active.has(e.id) ? <span className="text-accent">active</span> : <span className="text-ink-2">expired</span>}</td>
            <td><button type="button" aria-label={`forget ${e.id}`} onClick={() => forget.mutate(e.id)} className="text-xs text-danger">forget</button></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
