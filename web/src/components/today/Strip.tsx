import type { ReactNode } from "react";
import type { TodayView } from "../../api/queries";
import { Skeleton } from "./Card";
import SessionCard from "./SessionCard";
import ReadinessCard from "./ReadinessCard";
import FuelCard from "./FuelCard";
import WeekCard from "./WeekCard";

// Below lg the cards scroll sideways inside the strip, so the chat keeps the height.
function Slot({ children }: { children: ReactNode }) {
  return <div className="w-[82%] shrink-0 snap-start sm:w-[45%] lg:w-auto">{children}</div>;
}

export default function Strip({ today }: { today: TodayView | undefined }) {
  return (
    <div className="flex shrink-0 snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto border-b border-line px-4 py-4 lg:grid lg:grid-cols-4 lg:overflow-visible">
      {!today ? (
        <>
          <Slot><Skeleton /></Slot>
          <Slot><Skeleton /></Slot>
          <Slot><Skeleton /></Slot>
          <Slot><Skeleton /></Slot>
        </>
      ) : (
        <>
          <Slot><SessionCard session={today.session} /></Slot>
          <Slot><ReadinessCard readiness={today.readiness} /></Slot>
          <Slot><FuelCard fuel={today.fuel} /></Slot>
          <Slot><WeekCard week={today.week} /></Slot>
        </>
      )}
    </div>
  );
}
