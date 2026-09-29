import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { renderWith, todayFull } from "./fixtures";
import Shell from "../src/components/Shell";
import Header from "../src/components/Header";

function tree() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<div>today body</div>} />
        <Route path="/progress" element={<div>progress body</div>} />
        <Route path="/settings" element={<div>settings body</div>} />
      </Route>
    </Routes>
  );
}

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify(todayFull()), { status: 200 }));
});
afterEach(() => {
  vi.restoreAllMocks();
});

test("the shell's top bar shows today's header on every page", async () => {
  renderWith(tree(), { route: "/settings" });
  expect(await screen.findByText(/Wed, Sep 16/)).toBeInTheDocument();
});

test("the header shows date, phase and week, countdown, last sync and the pending badge", () => {
  const today = { ...todayFull(), pending: { narration: "n", proposals: [] } };
  renderWith(<Header today={today} />);
  expect(screen.getByText(/Wed, Sep 16/)).toBeInTheDocument();
  expect(screen.getByText(/active · week 1 of 3/)).toBeInTheDocument();
  expect(screen.getByText(/46 days to City Tri/)).toBeInTheDocument();
  expect(screen.getByText(/garmin/)).toBeInTheDocument();
  expect(screen.getByText("1 review pending")).toBeInTheDocument();
});

test("the header without a plan says so and shows no badge", () => {
  renderWith(<Header today={undefined} />);
  expect(screen.queryByText(/review pending/)).not.toBeInTheDocument();
});

test("a skip link targets main, and main takes focus after a route change", async () => {
  const user = userEvent.setup();
  renderWith(tree(), { route: "/progress" });
  expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute("href", "#main");
  const main = screen.getByRole("main");
  expect(main).not.toHaveFocus();
  await user.click(screen.getByRole("link", { name: "Settings" }));
  expect(main).toHaveFocus();
});

test("sync status says failed or stale in words, not only colour", () => {
  const t = todayFull();
  const at = Date.parse(t.header.last_sync[0].last_run_at);
  const failed = { ...t, header: { ...t.header, last_sync: [{ ...t.header.last_sync[0], status: "error", error: "401" }] } };
  const { unmount } = renderWith(<Header today={failed} now={at + 60_000} />);
  expect(screen.getByText(/garmin .* · failed/)).toHaveClass("text-danger");
  unmount();
  renderWith(<Header today={t} now={at + 25 * 3_600_000} />);
  expect(screen.getByText(/garmin .* · stale/)).toHaveClass("text-warn");
});

test("a fresh sync carries no status word", () => {
  const t = todayFull();
  renderWith(<Header today={t} now={Date.parse(t.header.last_sync[0].last_run_at) + 3_600_000} />);
  expect(screen.queryByText(/stale|failed/)).not.toBeInTheDocument();
});

test("the shell marks a sync stale from the fetch-time clock", async () => {
  const t = todayFull();
  t.header.last_sync[0].last_run_at = new Date(Date.now() - 2 * 86_400_000).toISOString();
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify(t), { status: 200 }));
  renderWith(tree(), { route: "/settings" });
  expect(await screen.findByText(/· stale/)).toBeInTheDocument();
});

test("the tabs show every section, mark the current one, and the jobs sit in the top bar", () => {
  renderWith(tree(), { route: "/progress" });
  const nav = screen.getByRole("navigation", { name: "Sections" });
  for (const name of ["Today", "Progress", "Nutrition", "Labs", "Settings"]) {
    expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
  }
  expect(within(nav).getByRole("link", { name: "Progress" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("button", { name: "Sync now" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Weekly check-in" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Account menu/ })).not.toBeInTheDocument();
});

test("the observations line takes a row of its own on a narrow screen, so the job buttons never sit on it", () => {
  renderWith(<Header today={todayFull()} />);
  expect(screen.getByText(/Wed, Sep 16/).parentElement).toHaveClass("basis-full", "sm:basis-0");
});

test("the pending badge and the job buttons wrap together instead of overflowing a phone", () => {
  const today = { ...todayFull(), pending: { narration: "n", proposals: [] } };
  renderWith(<Header today={today} slots={<button type="button">job</button>} />);
  expect(screen.getByText("1 review pending").parentElement).toHaveClass("flex-wrap");
});
