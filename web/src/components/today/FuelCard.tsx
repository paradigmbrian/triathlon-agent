import type { TodayView } from "../../api/queries";
import { day, kcal } from "../../lib/format";
import { Card, Empty, Headline } from "./Card";

export default function FuelCard({ fuel }: { fuel: TodayView["fuel"] }) {
  const t = fuel.target;
  return (
    <Card title="Fuel" tone="nutrition">
      {!t ? (
        <Empty>No targets yet, ask the coach</Empty>
      ) : (
        <>
          <Headline>{kcal(t.total_kcal)}</Headline>
          <div className="text-ink-2">
            {t.day_type} · {t.carbs_g} C · {t.protein_g} P · {t.fat_g} F · {t.fluid_baseline_ml} ml
          </div>
          <div className="text-xs text-ink-2">targets through {day(fuel.targets_through)}{t.written_to_garmin ? " · on Garmin" : ""}</div>
        </>
      )}
    </Card>
  );
}
