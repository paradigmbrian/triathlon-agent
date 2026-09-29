import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import VerdictStrip from "../src/components/board/VerdictStrip";
import Conditions from "../src/components/board/Conditions";
import type { ConditionOut, VerdictOut } from "../src/api/queries";
import { todayFull } from "./fixtures";

const easy: VerdictOut = {
  call: "easy",
  reasons: [{ key: "acwr", text: "ACWR 1.45, over 1.3", severity: "caution" }],
  based_on: "2026-09-16", stale: false, harder_than_call: true, session_done: false,
};

function Board({ verdict = easy, rows = todayFull().conditions }: { verdict?: VerdictOut; rows?: ConditionOut[] }) {
  const [active, setActive] = useState<string | null>(null);
  return (
    <>
      <VerdictStrip verdict={verdict} active={active} onActive={setActive} />
      <Conditions readiness={todayFull().readiness} rows={rows} reasons={verdict.reasons} active={active} onActive={setActive} />
    </>
  );
}

test.each([
  ["go", "GO", "text-go"],
  ["easy", "EASY", "text-easy"],
  ["rest", "REST", "text-rest"],
  ["none", "NO CALL", "text-ink-2"],
] as const)("the %s call reads %s in its colour", (call, word, tone) => {
  render(<Board verdict={{ ...easy, call, reasons: call === "go" ? [] : easy.reasons }} />);
  expect(screen.getByText(word)).toHaveClass(tone);
});

test("a go day says so in words", () => {
  render(<Board verdict={{ ...easy, call: "go", reasons: [], harder_than_call: false }} />);
  expect(screen.getByText("All conditions within your limits")).toBeInTheDocument();
});

test("the strip says when the data is old, when the plan is harder, and when the session is done", () => {
  render(<Board verdict={{ ...easy, stale: true, based_on: "2026-09-14", session_done: true }} />);
  expect(screen.getByText(/based on Mon, Sep 14/)).toBeInTheDocument();
  expect(screen.getByText("planned session is harder than today's call")).toBeInTheDocument();
  expect(screen.getByText("session done, recover")).toBeInTheDocument();
});

test("the conditions table shows each row's figures and status word", () => {
  render(<Board />);
  const table = screen.getByRole("table");
  expect(table).toBeInTheDocument();
  expect(screen.getByText("62 ms")).toBeInTheDocument();
  expect(screen.getByText("81")).toBeInTheDocument();
  expect(screen.getByText("7.5 h")).toBeInTheDocument();
  expect(screen.getByText("-4.9")).toBeInTheDocument();
  expect(screen.getByText("1.11")).toBeInTheDocument();
  expect(screen.getByText("+3.5/wk")).toBeInTheDocument();
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
  await user.tab(); // the first focusable element is the chip
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
