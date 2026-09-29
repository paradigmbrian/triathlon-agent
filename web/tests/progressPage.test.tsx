import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Progress from "../src/pages/Progress";
import { renderWith } from "./fixtures";
import { progressEmpty, progressFull } from "./progressFixtures";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
afterEach(() => vi.restoreAllMocks());

test("draws every chart and defaults to 12 months", async () => {
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async () => json(progressFull()));
  renderWith(<Progress />);
  expect(await screen.findByRole("heading", { name: "Performance management" })).toBeInTheDocument();
  for (const h of ["Fitness ramp rate", "Weekly volume by sport", "Longest workout by week", "Sport share"]) {
    expect(screen.getByRole("heading", { name: h })).toBeInTheDocument();
  }
  expect(screen.getByRole("radio", { name: "12 months" })).toBeChecked();
  expect(String(spy.mock.calls[0][0])).toBe("/api/progress?range=12m");
});

test("changing the range asks for it and never shows the old data under the new label", async () => {
  let release: (r: Response) => void = () => {};
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
    String(input).endsWith("range=6w") ? new Promise<Response>((r) => (release = r)) : Promise.resolve(json(progressFull())),
  );
  const user = userEvent.setup();
  renderWith(<Progress />);
  await screen.findByRole("heading", { name: "Performance management" });
  await user.click(screen.getByRole("radio", { name: "6 weeks" }));
  expect(String(spy.mock.calls.at(-1)![0])).toBe("/api/progress?range=6w");
  expect(screen.queryByRole("heading", { name: "Performance management" })).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  release(json({ ...progressFull(), range: "6w" }));
  expect(await screen.findByRole("heading", { name: "Performance management" })).toBeInTheDocument();
});

test("an error shows a message and retry refetches", async () => {
  const spy = vi.spyOn(globalThis, "fetch").mockImplementationOnce(async () => json({ detail: "internal error" }, 500));
  spy.mockImplementation(async () => json(progressFull()));
  const user = userEvent.setup();
  renderWith(<Progress />);
  expect(await screen.findByRole("alert")).toHaveTextContent(/could not load/i);
  await user.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByRole("heading", { name: "Performance management" })).toBeInTheDocument();
});

test("a fresh database shows empty states and no as-of date", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => json(progressEmpty()));
  renderWith(<Progress />);
  await screen.findByRole("heading", { name: "Performance management" });
  expect(screen.getAllByText("No data in this range.").length).toBeGreaterThanOrEqual(3);
  expect(screen.getByText(/No fitness readings yet/)).toBeInTheDocument();
});

test("a curve older than three days is flagged as stale", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => json({ ...progressFull(), as_of: "2026-09-10", end: "2026-09-16" }));
  renderWith(<Progress />);
  await waitFor(() => expect(screen.getByText(/6 days old/)).toBeInTheDocument());
  expect(screen.getByText(/Fitness as of/)).toBeInTheDocument();
});

test("a current curve is not flagged", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => json(progressFull()));
  renderWith(<Progress />);
  await screen.findByRole("heading", { name: "Performance management" });
  expect(screen.getByText(/Fitness as of/)).toBeInTheDocument();
  expect(screen.queryByText(/days old/)).not.toBeInTheDocument();
});
