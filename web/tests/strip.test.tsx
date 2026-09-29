import { screen } from "@testing-library/react";
import Strip from "../src/components/today/Strip";
import { renderWith, todayEmpty, todayFull } from "./fixtures";

test("every card has a sentence for its null state", () => {
  renderWith(<Strip today={todayEmpty()} />);
  expect(screen.getByText("No session planned")).toBeInTheDocument();
  expect(screen.getByText("No Garmin data yet, sync first")).toBeInTheDocument();
  expect(screen.getByText("No targets yet, ask the coach")).toBeInTheDocument();
  expect(screen.getByText("No plan; ask the coach to build one")).toBeInTheDocument();
});

test("the cards show today's numbers", () => {
  renderWith(<Strip today={todayFull()} />);
  expect(screen.getByText("Tempo")).toBeInTheDocument();
  expect(screen.getByText(/run · 1\.0 h · 60 TSS/)).toBeInTheDocument();
  expect(screen.getByText(/60 g\/h/)).toBeInTheDocument();
  expect(screen.getByText("81")).toBeInTheDocument(); // sleep score
  expect(screen.getByText(/7\.5 h/)).toBeInTheDocument();
  expect(screen.getByText(/45\.2 \/ 50\.1 \/ -4\.9/)).toBeInTheDocument();
  expect(screen.getByText(/2,900 kcal/)).toBeInTheDocument();
  expect(screen.getByText(/380 C · 150 P · 80 F/)).toBeInTheDocument();
  expect(screen.getByText(/2\.5 h of 6\.0 h/)).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42");
  expect(screen.getByText("run 1/2 · 60 of 120 TSS · 1.0 of 2.0 h")).toBeInTheDocument();
  expect(screen.getByText("bike 1/2 · 60 of 180 TSS · 1.5 of 4.0 h")).toBeInTheDocument();
});

test("readiness from an earlier day says which day", () => {
  const t = todayFull();
  t.readiness = { ...t.readiness!, is_today: false, date: "2026-09-14" };
  renderWith(<Strip today={t} />);
  expect(screen.getByText(/from Mon, Sep 14/)).toBeInTheDocument();
});

test("the strip shows skeletons while loading", () => {
  renderWith(<Strip today={undefined} />);
  expect(screen.getAllByTestId("card-skeleton")).toHaveLength(4);
});

test("readiness leads with training readiness and falls back to sleep score", () => {
  const { unmount } = renderWith(<Strip today={todayFull()} />);
  expect(screen.getByText("training readiness")).toBeInTheDocument();
  expect(screen.getByText("77")).toBeInTheDocument();
  unmount();
  const t = todayFull();
  t.readiness = { ...t.readiness!, training_readiness: null };
  renderWith(<Strip today={t} />);
  expect(screen.getByText("sleep score")).toBeInTheDocument();
  expect(screen.getAllByText("81")).toHaveLength(2); // headline and the sleep row
});

test("a trend row says how today compares, in words and colour", () => {
  const t = todayFull();
  t.readiness!.trends.hrv = { ...t.readiness!.trends.hrv, now: 50, band: "below", better: false };
  renderWith(<Strip today={t} />);
  const hrv = screen.getByText("↓8 low");
  expect(hrv).toHaveClass("text-warn");
  expect(hrv).toHaveTextContent("vs 28-day avg"); // screen-reader text
  expect(screen.getByText("↓2")).toHaveClass("text-good"); // RHR 48 vs 50, lower is better
  expect(screen.getByText("arrows: vs 28-day avg")).toBeInTheDocument();
});

test("the load line names the TSB zone and flags ramp and ACWR", () => {
  const t = todayFull();
  t.readiness = { ...t.readiness!, ramp_7d: 9.2, ramp_caution: true, acwr: 1.45, acwr_flag: "high" };
  renderWith(<Strip today={t} />);
  const tsb = screen.getByText("TSB -4.9 neutral");
  expect(tsb).toHaveClass("text-ink-2");
  const ramp = screen.getByText("ramp +9.2/wk fast");
  const acwr = screen.getByText("ACWR 1.45 high");
  expect(ramp).toHaveClass("text-warn");
  expect(acwr).toHaveClass("text-warn");
  expect(ramp.parentElement).toBe(tsb.parentElement); // one row of chips
  expect(acwr.parentElement).toBe(tsb.parentElement);
});

test("the readiness card copes with no trends and no load", () => {
  const t = todayFull();
  t.readiness = { ...t.readiness!, trends: {}, tsb: null, tsb_zone: null, ramp_7d: null, acwr: null, acwr_flag: null };
  renderWith(<Strip today={t} />);
  expect(screen.getByText("77")).toBeInTheDocument();
  expect(screen.queryByText(/vs 28-day avg/)).not.toBeInTheDocument();
  expect(screen.queryByText(/ramp|ACWR/)).not.toBeInTheDocument();
});

test("a completed session shows intensity, HR, power and percent of planned", () => {
  const t = todayFull();
  t.session!.workouts[0] = {
    ...t.session!.workouts[0],
    completed: true,
    actual_duration_sec: 3780,
    actual_tss: 57,
    actual_if: 0.82,
    avg_hr: 148,
    avg_power: 212,
    normalized_power: 225,
  };
  renderWith(<Strip today={t} />);
  expect(screen.getByText("IF 0.82 · 148 bpm · 212 W (NP 225)")).toBeInTheDocument();
  expect(screen.getByText("105% of planned time · 95% of planned TSS")).toBeInTheDocument();
});

test("the week shows sessions done so far, hidden before the first session", () => {
  const { unmount } = renderWith(<Strip today={todayFull()} />);
  expect(screen.getByText("2 of 3 so far")).toBeInTheDocument();
  unmount();
  const t = todayFull();
  t.week = { ...t.week!, planned_to_date: 0, completed_to_date: 0 };
  renderWith(<Strip today={t} />);
  expect(screen.queryByText(/so far/)).not.toBeInTheDocument();
});

test("skeletons pulse only when motion is allowed", () => {
  renderWith(<Strip today={undefined} />);
  expect(screen.getAllByTestId("card-skeleton")[0]).toHaveClass("motion-safe:animate-pulse");
});

test("the headline carries its own vs-28-day-avg context", () => {
  renderWith(<Strip today={todayFull()} />);
  expect(screen.getByText("↑7")).toHaveClass("text-good");
});

test("a delta that rounds to zero reads as level, not as an arrow", () => {
  const t = todayFull();
  t.readiness!.trends.hrv = { ...t.readiness!.trends.hrv, now: 57.6, avg_28d: 58, band: "normal", better: false };
  renderWith(<Strip today={t} />);
  expect(screen.getByText("=")).toHaveClass("text-ink-2");
  expect(screen.queryByText(/↓0/)).not.toBeInTheDocument();
});

test("a ramp that rounds to zero never shows a minus sign", () => {
  const t = todayFull();
  t.readiness = { ...t.readiness!, ramp_7d: -0.04 };
  renderWith(<Strip today={t} />);
  expect(screen.getByText("ramp 0.0/wk")).toBeInTheDocument();
});

test("the readiness card draws no sparklines", () => {
  const { container } = renderWith(<Strip today={todayFull()} />);
  expect(container.querySelector("polyline")).toBeNull();
});
