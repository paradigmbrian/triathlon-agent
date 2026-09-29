import { screen } from "@testing-library/react";
import Board from "../src/components/board/Board";
import { paused, renderWith, todayEmpty, todayFull } from "./fixtures";

test("every section has a sentence for its null state", () => {
  renderWith(<Board today={todayEmpty()} review={null} onHold={() => {}} />);
  expect(screen.getByText("No session planned")).toBeInTheDocument();
  expect(screen.getByText("No Garmin data yet, sync first")).toBeInTheDocument();
  expect(screen.getByText("No targets yet, ask the coach")).toBeInTheDocument();
  expect(screen.getByText("No plan; ask the coach to build one")).toBeInTheDocument();
});

test("the board shows today's numbers", () => {
  renderWith(<Board today={todayFull()} review={null} onHold={() => {}} />);
  expect(screen.getByText("Tempo")).toBeInTheDocument();
  expect(screen.getByText(/run · 1\.0 h · 60 TSS/)).toBeInTheDocument();
  expect(screen.getByText(/60 g\/h/)).toBeInTheDocument();
  expect(screen.getByText("81")).toBeInTheDocument(); // sleep score
  expect(document.getElementById("cond-sleep_hours")).toHaveTextContent("7.5 h");
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
  renderWith(<Board today={t} review={null} onHold={() => {}} />);
  expect(screen.getByText(/from Mon, Sep 14/)).toBeInTheDocument();
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
  renderWith(<Board today={t} review={null} onHold={() => {}} />);
  expect(screen.getByText("IF 0.82 · 148 bpm · 212 W (NP 225)")).toBeInTheDocument();
  expect(screen.getByText("105% of planned time · 95% of planned TSS")).toBeInTheDocument();
});

test("the week shows sessions done so far, hidden before the first session", () => {
  const { unmount } = renderWith(<Board today={todayFull()} review={null} onHold={() => {}} />);
  expect(screen.getByText("2 of 3 so far")).toBeInTheDocument();
  unmount();
  const t = todayFull();
  t.week = { ...t.week!, planned_to_date: 0, completed_to_date: 0 };
  renderWith(<Board today={t} review={null} onHold={() => {}} />);
  expect(screen.queryByText(/so far/)).not.toBeInTheDocument();
});

test("the board shows a loading line before today arrives", () => {
  renderWith(<Board today={undefined} review={null} onHold={() => {}} />);
  expect(screen.getByText("Loading today…")).toBeInTheDocument();
});

test("the HOLD line appears only while a review waits", () => {
  const hold = vi.fn();
  const { unmount } = renderWith(<Board today={todayFull()} review={null} onHold={hold} />);
  expect(screen.queryByText(/HOLD/)).not.toBeInTheDocument();
  unmount();
  renderWith(<Board today={todayFull()} review={{ narration: "n", proposals: [paused().proposals[0]] }} onHold={hold} />);
  screen.getByRole("button", { name: "HOLD · 1 change awaiting your approval" }).click();
  expect(hold).toHaveBeenCalledOnce();
});
