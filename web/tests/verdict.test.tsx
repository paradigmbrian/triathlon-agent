import { useState } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReadinessStatus from "../src/components/board/ReadinessStatus";
import Conditions from "../src/components/board/Conditions";
import type { ConditionOut, VerdictOut } from "../src/api/queries";
import { todayFull } from "./fixtures";

const base: VerdictOut = {
  level: "moderate",
  reasons: [{ key: "acwr", text: "ACWR 1.45, over 1.3", severity: "caution" }],
  based_on: "2026-09-16", stale: false, harder_than_call: true, session_done: false,
};

// The page's order: the metrics first, then the readiness container.
function Board({ verdict = base, rows = todayFull().conditions }: { verdict?: VerdictOut; rows?: ConditionOut[] }) {
  const [active, setActive] = useState<string | null>(null);
  return (
    <>
      <Conditions readiness={todayFull().readiness} rows={rows} reasons={verdict.reasons} active={active} onActive={setActive} />
      <ReadinessStatus verdict={verdict} active={active} onActive={setActive} />
    </>
  );
}

test.each([
  ["prime", "PRIME", "text-go"],
  ["high", "HIGH", "text-go"],
  ["moderate", "MODERATE", "text-easy"],
  ["low", "LOW", "text-rest"],
  ["poor", "POOR", "text-rest"],
  ["none", "NO READING", "text-ink-2"],
] as const)("the %s level reads %s in its colour", (level, word, tone) => {
  render(<Board verdict={{ ...base, level, reasons: [] }} />);
  expect(screen.getByText(word)).toHaveClass(tone);
  expect(screen.getByText(word)).toHaveClass("text-2xl");
});

test("the scale lights only the current step and always shows every label", () => {
  const { unmount } = render(<Board verdict={{ ...base, level: "moderate" }} />);
  const scale = screen.getByRole("list", { name: "Readiness scale" });
  const steps = within(scale).getAllByRole("listitem");
  expect(steps.map((li) => li.textContent)).toEqual(["Poor", "Low", "Moderate", "High", "Prime"]);
  expect(steps.filter((li) => li.getAttribute("aria-current") === "true")).toHaveLength(1);
  const current = within(scale).getByText("Moderate").closest("li")!;
  expect(current).toHaveAttribute("aria-current", "true");
  expect(current.querySelector("[data-bar]")).toHaveClass("bg-easy");
  expect(within(scale).getByText("High").closest("li")!.querySelector("[data-bar]")).toHaveClass("bg-line");
  unmount();
  render(<Board verdict={{ ...base, level: "none", reasons: [] }} />);
  const none = within(screen.getByRole("list", { name: "Readiness scale" })).getAllByRole("listitem");
  expect(none.filter((li) => li.getAttribute("aria-current") === "true")).toHaveLength(0);
});

test("an all-clear says so in words", () => {
  render(<Board verdict={{ ...base, level: "prime", reasons: [], harder_than_call: false }} />);
  expect(screen.getByText("All conditions within your limits")).toBeInTheDocument();
});

test("a level held down only by Garmin's score explains itself", () => {
  const info = { key: "training_readiness", text: "Garmin readiness 62, moderate band", severity: "info" } as const;
  render(<Board verdict={{ ...base, level: "moderate", reasons: [info], harder_than_call: false }} />);
  expect(screen.getByText("All conditions within your limits")).toBeInTheDocument(); // no flags
  expect(screen.getByText("Garmin readiness 62, moderate band")).toBeInTheDocument();
  expect(document.getElementById("reason-training_readiness")).not.toBeNull();
  expect(document.getElementById("cond-training_readiness")).toHaveAttribute("aria-describedby", "reason-training_readiness");
});

test("the container says when the data is old, when the plan is harder, and when the session is done", () => {
  render(<Board verdict={{ ...base, stale: true, based_on: "2026-09-14", session_done: true }} />);
  expect(screen.getByText(/based on Mon, Sep 14/)).toBeInTheDocument();
  expect(screen.getByText("planned session is harder than today's call")).toBeInTheDocument();
  expect(screen.getByText("session done, recover")).toBeInTheDocument();
});

test("the conditions table shows each row's figures and status word", () => {
  render(<Board />);
  const table = screen.getByRole("table");
  expect(table).toBeInTheDocument();
  expect(document.getElementById("cond-hrv")).toHaveTextContent("62 ms");
  expect(screen.getByText("81")).toBeInTheDocument();
  expect(document.getElementById("cond-sleep_hours")).toHaveTextContent("7.5 h");
  expect(screen.getByText("-4.9")).toBeInTheDocument();
  expect(screen.getByText("1.11")).toBeInTheDocument();
  expect(document.getElementById("cond-ramp")).toHaveTextContent("+3.5/wk");
  expect(screen.getByText("neutral")).toBeInTheDocument();
  expect(screen.getAllByText("within").length).toBeGreaterThan(0);
});

test("a flagged row's status word takes its reason's colour", () => {
  const rows = todayFull().conditions.map((c) => (c.key === "acwr" ? { ...c, value: 1.45, status: "high", flagged: true } : c));
  render(<Board rows={rows} />);
  const row = document.getElementById("cond-acwr")!;
  expect(row).toHaveTextContent("high");
  expect(row.querySelector("[data-status]")).toHaveClass("text-easy");
});

test("the table says 'No Garmin data yet, sync first' when there are no rows", () => {
  render(<Conditions readiness={null} rows={[]} reasons={[]} active={null} onActive={() => {}} />);
  expect(screen.getByText("No Garmin data yet, sync first")).toBeInTheDocument();
});

test("a reason chip and its row light each other, by keyboard too", async () => {
  const user = userEvent.setup();
  render(<Board />);
  const chip = screen.getByRole("button", { name: "ACWR 1.45, over 1.3" });
  const row = document.getElementById("cond-acwr")!;
  act(() => chip.focus()); // the chip now follows the table in tab order
  expect(chip).toHaveFocus();
  expect(row).toHaveAttribute("data-active", "true");
  await user.keyboard("{Enter}");
  expect(row).toHaveFocus();
  expect(chip).toHaveAttribute("data-active", "true");
  expect(row).toHaveAttribute("aria-describedby", "reason-acwr");
  fireEvent.mouseLeave(row);
  fireEvent.blur(row);
  expect(row).toHaveAttribute("data-active", "false");
});

test("rows flash only when a value changes after the first render", () => {
  const rows = todayFull().conditions;
  const { rerender } = render(<Conditions readiness={null} rows={rows} reasons={[]} active={null} onActive={() => {}} />);
  expect(document.querySelectorAll(".board-flash")).toHaveLength(0);
  const next = rows.map((c) => (c.key === "hrv" ? { ...c, value: 64 } : c));
  rerender(<Conditions readiness={null} rows={next} reasons={[]} active={null} onActive={() => {}} />);
  const flashing = Array.from(document.querySelectorAll(".board-flash")).map((el) => el.closest("tr")!.id);
  expect(flashing).toEqual(["cond-hrv"]);
});

test("rows from an earlier day say which day", () => {
  const t = todayFull();
  render(<Conditions readiness={{ ...t.readiness!, is_today: false, date: "2026-09-14" }} rows={t.conditions} reasons={[]} active={null} onActive={() => {}} />);
  expect(screen.getByText(/from Mon, Sep 14/)).toBeInTheDocument();
});

test("a no-call reason is plain text, not a button that goes nowhere", () => {
  const none: VerdictOut = {
    level: "none",
    reasons: [{ key: "training_readiness", text: "No Garmin data, sync first", severity: "info" }],
    based_on: null, stale: false, harder_than_call: false, session_done: false,
  };
  render(<ReadinessStatus verdict={none} active={null} onActive={() => {}} />);
  expect(screen.getByText("No Garmin data, sync first")).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(screen.queryByText("All conditions within your limits")).not.toBeInTheDocument();
});

test("each row wears its state: a rail and a large figure in the same colour, the unit small", () => {
  const rows = todayFull().conditions.map((c) => (c.key === "acwr" ? { ...c, value: 1.45, status: "high", flagged: true } : c));
  render(<Board rows={rows} />);
  const fig = (key: string) => document.querySelector(`#cond-${key} [data-figure]`)!;
  const rail = (key: string) => document.querySelector(`#cond-${key} th[scope="row"]`)!;
  expect(fig("hrv")).toHaveClass("text-4xl", "font-semibold");
  expect(fig("hrv").textContent).toBe("62"); // the unit is its own smaller element
  expect(document.querySelector("#cond-hrv [data-unit]")).toHaveClass("text-sm");
  // inside your band: go. above the band but not flagged: hold. flagged: its reason's colour. no band word: plain.
  expect(fig("sleep_score")).toHaveClass("text-go");
  expect(rail("sleep_score")).toHaveClass("border-go");
  expect(fig("hrv")).toHaveClass("text-hold");
  expect(rail("hrv")).toHaveClass("border-hold");
  expect(fig("acwr")).toHaveClass("text-easy");
  expect(rail("acwr")).toHaveClass("border-easy");
  expect(fig("tsb")).not.toHaveClass("text-go", "text-hold", "text-easy", "text-rest");
  expect(rail("tsb")).toHaveClass("border-line");
});

test("Figures is the default view, and Trends swaps the columns for a line per row", async () => {
  const user = userEvent.setup();
  render(<Board />);
  const figures = screen.getByRole("button", { name: "Figures" });
  const trends = screen.getByRole("button", { name: "Trends" });
  expect(figures).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("columnheader", { name: "28-day" })).toBeInTheDocument();
  expect(document.querySelectorAll("svg[data-trend]")).toHaveLength(0);
  await user.click(trends);
  expect(trends).toHaveAttribute("aria-pressed", "true");
  expect(figures).toHaveAttribute("aria-pressed", "false");
  expect(screen.queryByRole("columnheader", { name: "28-day" })).not.toBeInTheDocument();
  expect(document.querySelectorAll("svg[data-trend]")).toHaveLength(5); // the five rows with history
  expect(screen.getAllByText("no history")).toHaveLength(3); // Form, ACWR, Ramp
  expect(document.getElementById("cond-hrv")).toHaveTextContent("62 ms"); // the figure and the status word stay
  expect(document.getElementById("cond-hrv")).toHaveTextContent("high");
});

test("a trend line breaks at a missing day and marks today's value", async () => {
  const user = userEvent.setup();
  render(<Board />);
  await user.click(screen.getByRole("button", { name: "Trends" }));
  const svg = document.querySelector("#cond-hrv svg[data-trend]")!;
  expect(svg.querySelectorAll("polyline")).toHaveLength(2); // one gap, so two runs
  expect(svg.querySelectorAll("circle")).toHaveLength(1);
  expect(svg.querySelector("rect[data-band]")).not.toBeNull();
  expect(svg).toHaveAttribute("aria-hidden", "true");
});

test("chips still find their row in the Trends view", async () => {
  const user = userEvent.setup();
  render(<Board />);
  await user.click(screen.getByRole("button", { name: "Trends" }));
  await user.click(screen.getByRole("button", { name: "ACWR 1.45, over 1.3" }));
  expect(document.getElementById("cond-acwr")).toHaveFocus();
});
