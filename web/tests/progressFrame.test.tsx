import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChartFrame from "../src/components/progress/ChartFrame";
import RangePicker from "../src/components/progress/RangePicker";
import Scrubber from "../src/components/progress/Scrubber";

test("ChartFrame shows the summary and swaps the chart for a table on toggle", async () => {
  const user = userEvent.setup();
  render(
    <ChartFrame title="Weekly volume" summary="Average 4 mi per week." table={{ head: ["Week", "mi"], rows: [["Sep 7", 4]] }}>
      <svg data-testid="chart" />
    </ChartFrame>,
  );
  expect(screen.getByRole("heading", { name: "Weekly volume" })).toBeInTheDocument();
  expect(screen.getByText("Average 4 mi per week.")).toBeInTheDocument();
  expect(screen.getByTestId("chart")).toBeInTheDocument();
  const toggle = screen.getByRole("button", { name: "View as table" });
  expect(toggle).toHaveAttribute("aria-pressed", "false");
  await user.click(toggle);
  expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
  expect(screen.getByRole("table", { name: "Weekly volume" })).toBeInTheDocument();
  expect(screen.getByRole("rowheader", { name: "Sep 7" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "View as chart" })).toHaveAttribute("aria-pressed", "true");
});

test("RangePicker marks the current range and reports a change", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(<RangePicker value="12m" onChange={onChange} />);
  expect(screen.getByRole("radio", { name: "12 months" })).toBeChecked();
  await user.click(screen.getByRole("radio", { name: "6 weeks" }));
  expect(onChange).toHaveBeenCalledWith("6w");
});

test("Scrubber reports the chosen point and is hidden for fewer than two points", () => {
  const onChange = vi.fn();
  const { rerender } = render(<Scrubber label="Inspect week" count={3} index={0} valueText="Sep 7" onChange={onChange} />);
  const slider = screen.getByRole("slider", { name: "Inspect week" });
  expect(slider).toHaveAttribute("aria-valuetext", "Sep 7");
  fireEvent.change(slider, { target: { value: "1" } }); // jsdom has no arrow-key stepping; the browser test covers the keys
  expect(onChange).toHaveBeenCalledWith(1);
  rerender(<Scrubber label="Inspect week" count={1} index={0} valueText="" onChange={onChange} />);
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
});
