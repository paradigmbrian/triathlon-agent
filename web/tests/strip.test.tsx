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
  expect(screen.getByText(/run 1\/2 · bike 1\/2/)).toBeInTheDocument();
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
