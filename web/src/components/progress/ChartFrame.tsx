import { useId, useState, type ReactNode } from "react";

export type ChartTable = { head: string[]; rows: (string | number)[][] };

/** A titled card for one chart: a sentence that states the point, optional controls, the chart or its data table. */
export default function ChartFrame({ title, summary, table, controls, children }: {
  title: string;
  summary: string;
  table: ChartTable;
  controls?: ReactNode;
  children: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  const id = useId();
  return (
    <section aria-labelledby={id} className="rounded-md border border-line bg-surface-2 px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h2 id={id} className="text-xs font-medium tracking-wider text-ink-2 uppercase">{title}</h2>
          <p className="mt-1 text-sm">{summary}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {controls}
          <button
            type="button"
            aria-pressed={asTable}
            onClick={() => setAsTable((v) => !v)}
            className="min-h-7 rounded-sm border border-line px-3 text-xs text-ink-2 hover:text-ink"
          >
            {asTable ? "View as chart" : "View as table"}
          </button>
        </div>
      </div>
      <div className="mt-3">
        {asTable ? (
          <div className="max-h-80 overflow-auto">
            <table className="w-full text-left text-xs tabular-nums">
              <caption className="sr-only">{title}</caption>
              <thead className="sticky top-0 bg-surface-2 text-ink-2">
                <tr>{table.head.map((h) => <th key={h} scope="col" className="py-1 pr-4 font-medium">{h}</th>)}</tr>
              </thead>
              <tbody>
                {table.rows.map((r, i) => (
                  <tr key={i} className="border-t border-line">
                    {r.map((c, j) => (j === 0 ? <th key={j} scope="row" className="py-1 pr-4 font-normal">{c}</th> : <td key={j} className="py-1 pr-4">{c}</td>))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          children
        )}
      </div>
    </section>
  );
}
