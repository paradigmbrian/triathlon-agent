import { useSearchParams } from "react-router";
import { useProgress, type ProgressRange } from "../api/queries";
import LongestWorkout from "../components/progress/LongestWorkout";
import Pmc from "../components/progress/Pmc";
import RampRates from "../components/progress/RampRates";
import RangePicker from "../components/progress/RangePicker";
import ShareBars from "../components/progress/ShareBars";
import WeeklyBars from "../components/progress/WeeklyBars";
import { day } from "../lib/format";

const RANGES: ProgressRange[] = ["6w", "6m", "12m", "all"];
const STALE_DAYS = 3; // mirrors STALE_DAYS in tri_web/progress.py

const daysBetween = (a: string, b: string) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);

export default function Progress() {
  const [params, setParams] = useSearchParams();
  const asked = params.get("range");
  const range: ProgressRange = RANGES.includes(asked as ProgressRange) ? (asked as ProgressRange) : "12m";
  const q = useProgress(range);
  const view = q.data;
  const age = view?.as_of ? daysBetween(view.as_of, view.end) : null;
  return (
    <section className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-sm font-semibold tracking-wide uppercase">Progress</h1>
        <RangePicker value={range} onChange={(r) => setParams({ range: r }, { replace: true })} />
      </div>
      {view && (
        <p className="mt-2 text-xs text-ink-2">
          {view.as_of ? `Fitness as of ${day(view.as_of)}` : "No fitness readings yet"}
          {age != null && age > STALE_DAYS && <span className="ml-2 font-medium text-warn">{age} days old: sync for fresh numbers</span>}
        </p>
      )}
      {q.isPending && <p role="status" className="mt-6 text-sm text-ink-2">Loading progress…</p>}
      {q.isError && (
        <div role="alert" className="mt-6 flex flex-wrap items-center gap-3 text-sm">
          <span>Could not load progress.</span>
          <button type="button" onClick={() => q.refetch()} className="min-h-8 rounded-sm border border-line px-3 text-xs hover:text-ink">Retry</button>
        </div>
      )}
      {view && (
        <div className="mt-2">
          <Pmc pmc={view.pmc} ramp28={view.ramp.find((r) => r.days === 28)?.delta ?? null} />
          <RampRates ramp={view.ramp} />
          <WeeklyBars weeks={view.weeks} />
          <LongestWorkout weeks={view.weeks} />
          <ShareBars share={view.share} />
        </div>
      )}
    </section>
  );
}
