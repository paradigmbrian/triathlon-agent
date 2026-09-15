import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { renderWith, todayFull } from "./fixtures";
import Shell from "../src/components/Shell";
import Header from "../src/components/Header";
import Placeholder from "../src/pages/Placeholder";

function tree() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<div>today body</div>} />
        <Route path="/progress" element={<Placeholder name="Progress" subProject={2} />} />
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

test("the avatar menu holds the five sections, marks the current one, and the two jobs", async () => {
  const user = userEvent.setup();
  renderWith(tree(), { route: "/progress" });
  expect(screen.getByText(/arrives in sub-project 2/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Progress" })).not.toBeInTheDocument();
  const avatar = screen.getByRole("button", { name: "Account menu" });
  expect(avatar).toHaveAttribute("aria-expanded", "false");
  await user.click(avatar);
  expect(avatar).toHaveAttribute("aria-expanded", "true");
  for (const name of ["Today", "Progress", "Nutrition", "Labs", "Settings"]) {
    expect(screen.getByRole("link", { name })).toBeInTheDocument();
  }
  expect(screen.getByRole("link", { name: "Progress" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("button", { name: "Sync now" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Weekly check-in" })).toBeInTheDocument();
});

test("the menu closes on Escape, on an outside click, and after following a link", async () => {
  const user = userEvent.setup();
  renderWith(tree(), { route: "/progress" });
  const avatar = screen.getByRole("button", { name: "Account menu" });

  await user.click(avatar);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();
  expect(avatar).toHaveFocus();

  await user.click(avatar);
  await user.click(screen.getByText(/arrives in sub-project 2/));
  expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();

  await user.click(avatar);
  await user.click(screen.getByRole("link", { name: "Settings" }));
  expect(screen.getByText("settings body")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();
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
