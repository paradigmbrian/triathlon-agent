import { useState } from "react";
import type { ReviewPayload, TodayView } from "../../api/queries";
import Conditions from "./Conditions";
import HoldLine from "./HoldLine";
import Plan from "./Plan";
import ReadinessStatus from "./ReadinessStatus";
import Week from "./Week";

type Props = { today: TodayView | undefined; review: ReviewPayload | null; onHold: () => void };

export default function Board({ today, review, onHold }: Props) {
  const [active, setActive] = useState<string | null>(null);
  if (!today) return <p role="status" className="px-6 py-6 text-sm text-ink-2">Loading today…</p>;
  return (
    <div className="mx-auto w-full max-w-5xl pb-10">
      <Conditions readiness={today.readiness} rows={today.conditions} reasons={today.verdict.reasons} level={today.verdict.level} active={active} onActive={setActive} />
      <ReadinessStatus verdict={today.verdict} active={active} onActive={setActive} />
      {review && <HoldLine count={review.proposals.length} onGo={onHold} />}
      <Plan session={today.session} fuel={today.fuel} />
      <Week week={today.week} />
    </div>
  );
}
