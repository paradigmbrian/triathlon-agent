import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Today from "../src/pages/Today";
import { paused, renderWith, threadEmpty, todayFull } from "./fixtures";

function stub(thread = threadEmpty()) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const body = url === "/api/today" ? { ...todayFull(), pending: thread.paused } : url === "/api/coach/thread" ? thread : {};
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  });
}
afterEach(() => vi.restoreAllMocks());

test("the coach toggle opens the panel and Escape closes it", async () => {
  stub();
  const user = userEvent.setup();
  renderWith(<Today />);
  const toggle = await screen.findByRole("button", { name: "Coach" });
  const panel = screen.getByRole("complementary", { name: "Coach" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(panel).toHaveClass("hidden");
  await user.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(panel).not.toHaveClass("hidden");
  await user.keyboard("{Escape}");
  expect(toggle).toHaveAttribute("aria-expanded", "false");
});

test("closing the coach returns focus to the Coach toggle", async () => {
  stub();
  const user = userEvent.setup();
  renderWith(<Today />);
  const toggle = await screen.findByRole("button", { name: "Coach" });
  await user.click(toggle);
  await user.click(screen.getByRole("button", { name: "Back to board" }));
  expect(toggle).toHaveFocus();
  await user.click(toggle);
  await user.keyboard("{Escape}");
  expect(toggle).toHaveFocus();
});

test("hold opens the coach and focuses the gate", async () => {
  stub({ ...threadEmpty(), paused: paused() });
  const user = userEvent.setup();
  renderWith(<Today />);
  await user.click(await screen.findByRole("button", { name: /HOLD · 1 change awaiting your approval/ }));
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  expect(screen.getByRole("button", { name: /Coach/ })).toHaveAttribute("aria-expanded", "true");
  expect(document.getElementById("review-gate")).toHaveFocus();
});
