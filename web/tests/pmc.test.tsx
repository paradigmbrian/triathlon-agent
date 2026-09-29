import { fireEvent, render, screen } from "@testing-library/react";
import Pmc from "../src/components/progress/Pmc";
import RampRates from "../src/components/progress/RampRates";
import { progressEmpty, progressFull } from "./progressFixtures";

test("Pmc states the latest CTL and form and breaks the line at the gap", () => {
  const p = progressFull();
  const { container } = render(<Pmc pmc={p.pmc} ramp28={null} />);
  expect(screen.getByText("CTL 40.0; form −5.0.")).toBeInTheDocument();
  // 12, 13 | gap | 15, 16: two CTL runs
  expect(container.querySelectorAll("path[data-series='ctl']")).toHaveLength(2);
});

test("Pmc adds the 28-day change to the summary when known", () => {
  const p = progressFull();
  render(<Pmc pmc={p.pmc} ramp28={2.5} />);
  expect(screen.getByText(/\+2\.5 over 28 days/)).toBeInTheDocument();
});

test("the scrubber reads a day's values and a gap day says no reading", () => {
  render(<Pmc pmc={progressFull().pmc} ramp28={null} />);
  const slider = screen.getByRole("slider", { name: "Inspect day" });
  expect(slider).toHaveValue("4");
  expect(screen.getByTestId("pmc-readout")).toHaveTextContent("CTL 40.0 · ATL 45.0 · TSB −5.0");
  fireEvent.change(slider, { target: { value: "2" } });
  expect(screen.getByTestId("pmc-readout")).toHaveTextContent("no reading");
});

test("Pmc with no CTL at all says so and draws no series", () => {
  const { container } = render(<Pmc pmc={progressEmpty().pmc} ramp28={null} />);
  expect(screen.getAllByText("No data in this range.").length).toBeGreaterThanOrEqual(1);
  expect(container.querySelectorAll("path[data-series]")).toHaveLength(0);
});

test("RampRates shows four signed tiles and a dash for a missing delta", () => {
  render(<RampRates ramp={progressFull().ramp} />);
  const tiles = screen.getAllByRole("group");
  expect(tiles).toHaveLength(4);
  expect(tiles[0]).toHaveTextContent("+1.5");
  expect(tiles[0]).toHaveTextContent("Last 7 days");
  expect(tiles[1]).toHaveTextContent("–");
  expect(tiles[2]).toHaveTextContent("−4.0");
  expect(tiles[3]).toHaveTextContent("Last 365 days");
});
