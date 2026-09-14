import type { TodayView } from "../../api/queries";
import { Skeleton } from "./Card";
import SessionCard from "./SessionCard";
import ReadinessCard from "./ReadinessCard";
import FuelCard from "./FuelCard";
import WeekCard from "./WeekCard";

export default function Strip({ today }: { today: TodayView | undefined }) {
  return (
    <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
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
