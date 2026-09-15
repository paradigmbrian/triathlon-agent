import type { TodayView } from "../../api/queries";
import { Skeleton } from "./Card";
import SessionCard from "./SessionCard";
import ReadinessCard from "./ReadinessCard";
import FuelCard from "./FuelCard";
import WeekCard from "./WeekCard";

export default function Strip({ today }: { today: TodayView | undefined }) {
  return (
    <div className="grid shrink-0 grid-cols-1 content-start gap-3 border-b border-line p-4 sm:grid-cols-2 md:w-80 md:grid-cols-1 md:overflow-y-auto md:border-r md:border-b-0 xl:w-96">
      {!today ? (
        <>
          <Skeleton /> <Skeleton /> <Skeleton /> <Skeleton />
        </>
      ) : (
        <>
          <SessionCard session={today.session} />
          <ReadinessCard readiness={today.readiness} />
          <FuelCard fuel={today.fuel} />
          <WeekCard week={today.week} />
        </>
      )}
    </div>
  );
}
