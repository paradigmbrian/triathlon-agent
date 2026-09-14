import { screen } from "@testing-library/react";
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

test("the rail links the five sections and marks the current one", () => {
  renderWith(tree(), { route: "/progress" });
  for (const name of ["Today", "Progress", "Nutrition", "Labs", "Settings"]) {
    expect(screen.getByRole("link", { name })).toBeInTheDocument();
  }
  expect(screen.getByRole("link", { name: "Progress" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByText(/arrives in sub-project 2/)).toBeInTheDocument();
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
