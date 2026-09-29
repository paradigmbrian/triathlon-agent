import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ShareBars from "../src/components/progress/ShareBars";
import { progressEmpty, progressFull } from "./progressFixtures";

test("each sport shows its percentage of completed and of planned duration", () => {
  render(<ShareBars share={progressFull().share} />);
  // completed: bike 10800, run 5400, brick 1800 -> other; total 18000
  const bike = screen.getByRole("group", { name: "Bike" });
  expect(bike).toHaveTextContent("Completed 60.0%");
  expect(bike).toHaveTextContent("Planned 62.5%"); // 12000 / 19200
  expect(screen.getByRole("group", { name: "Other" })).toHaveTextContent("Completed 10.0%");
  expect(screen.getByRole("group", { name: "Other" })).toHaveTextContent("Planned 0.0%");
});

test("switching to distance re-bases the shares on distance", async () => {
  const user = userEvent.setup();
  render(<ShareBars share={progressFull().share} />);
  await user.click(screen.getByRole("radio", { name: "Distance" }));
  // completed distance: bike 72420, run 15000 -> bike 82.8%
  expect(screen.getByRole("group", { name: "Bike" })).toHaveTextContent("Completed 82.8%");
});

test("sports with no share are left out and the summary names the leader", () => {
  render(<ShareBars share={progressFull().share} />);
  expect(screen.queryByRole("group", { name: "Swim" })).not.toBeInTheDocument();
  expect(screen.getByText(/Bike is 60\.0% of completed duration/)).toBeInTheDocument();
});

test("the bar widths follow the percentage", () => {
  render(<ShareBars share={progressFull().share} />);
  const bar = within(screen.getByRole("group", { name: "Bike" })).getAllByTestId("share-bar")[0];
  expect(bar).toHaveStyle({ width: "60%" });
});

test("empty shares say so and draw no bars", () => {
  render(<ShareBars share={progressEmpty().share} />);
  expect(screen.getAllByText("No data in this range.").length).toBeGreaterThanOrEqual(1);
  expect(screen.queryAllByTestId("share-bar")).toHaveLength(0);
});

test("with nothing completed but a plan, the summary speaks for the plan and does not say no data", () => {
  const share = progressFull().share;
  render(<ShareBars share={{ ...share, completed: { duration_sec: {}, distance_m: {} } }} />);
  expect(screen.queryByText("No data in this range.")).not.toBeInTheDocument();
  expect(screen.getByText(/Nothing completed yet; Bike is 62\.5% of planned duration/)).toBeInTheDocument();
});
