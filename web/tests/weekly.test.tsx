import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LongestWorkout from "../src/components/progress/LongestWorkout";
import WeeklyBars from "../src/components/progress/WeeklyBars";
import { progressEmpty, progressFull } from "./progressFixtures";

test("WeeklyBars totals distance in miles and averages only the complete weeks", () => {
  render(<WeeklyBars weeks={progressFull().weeks} />);
  // week 1: (48280 + 10000) m = 36.2 mi; week 2: (24140 + 5000) m = 18.1 mi; partial week 3 excluded
  expect(screen.getByText(/Average 27\.2 mi per week over 2 complete weeks/)).toBeInTheDocument();
});

test("the metric switch changes the unit", async () => {
  const user = userEvent.setup();
  render(<WeeklyBars weeks={progressFull().weeks} />);
  await user.click(screen.getByRole("radio", { name: "Duration" }));
  expect(screen.getByText(/Average 2\.[23] h per week/)).toBeInTheDocument();
  await user.click(screen.getByRole("radio", { name: "Elevation" }));
  expect(screen.getByText(/ft per week/)).toBeInTheDocument();
});

test("the partial week is labelled in the readout, and an unknown sport shows as Other", () => {
  render(<WeeklyBars weeks={progressFull().weeks} />);
  expect(screen.getByTestId("weekly-readout")).toHaveTextContent(/partial/i);
  fireEvent.change(screen.getByRole("slider", { name: "Inspect week" }), { target: { value: "1" } });
  expect(screen.getByTestId("weekly-readout")).toHaveTextContent(/Other 3\.1 mi/);
  expect(screen.getByTestId("weekly-readout")).not.toHaveTextContent(/brick/i);
});

test("the legend names every drawn sport with a marker", () => {
  render(<WeeklyBars weeks={progressFull().weeks} />);
  const legend = screen.getByRole("list");
  for (const s of ["Bike", "Run", "Other"]) expect(within(legend).getByText(s)).toBeInTheDocument();
  expect(within(legend).queryByText("Swim")).not.toBeInTheDocument();
});

test("the table lists every week with a column per sport", async () => {
  const user = userEvent.setup();
  render(<WeeklyBars weeks={progressFull().weeks} />);
  await user.click(screen.getByRole("button", { name: "View as table" }));
  expect(screen.getAllByRole("row")).toHaveLength(4); // header + 3 weeks
  expect(screen.getByRole("columnheader", { name: "Bike" })).toBeInTheDocument();
});

test("a single week draws with no scrubber and no NaN", () => {
  const one = progressFull().weeks.slice(0, 1);
  const { container } = render(<WeeklyBars weeks={one} />);
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
});

test("an empty range says so", () => {
  render(<WeeklyBars weeks={progressEmpty().weeks} />);
  expect(screen.getAllByText("No data in this range.").length).toBeGreaterThanOrEqual(1);
});

test("LongestWorkout switches between duration and distance and states the longest", async () => {
  const user = userEvent.setup();
  render(<LongestWorkout weeks={progressFull().weeks} />);
  expect(screen.getByText(/Longest: 30\.0 mi/)).toBeInTheDocument();
  await user.click(screen.getByRole("radio", { name: "Duration" }));
  expect(screen.getByText(/Longest: 2\.0 h/)).toBeInTheDocument();
});
