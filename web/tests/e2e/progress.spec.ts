import { expect, test, type Page } from "@playwright/test";

const week = (start: string, partial = false) => ({
  week_start: start, partial,
  by_sport: { bike: { duration_sec: 3600, distance_m: 30000, elevation_m: 100, calories: 600, tss: 50 } },
  longest: { duration_sec: 3600, distance_m: 30000 },
});
const progress = (range: string) => ({
  range, start: "2026-09-07", end: "2026-09-16", as_of: "2026-09-16",
  pmc: [
    { date: "2026-09-15", ctl: 39, atl: 44, tsb: -5, tss: 50 },
    { date: "2026-09-16", ctl: 40, atl: 45, tsb: -5, tss: 60 },
  ],
  ramp: [7, 28, 90, 365].map((days) => ({ days, delta: 1, series: [39, 40] })),
  weeks: [week("2026-09-07"), week("2026-09-14", true)],
  share: { completed: { duration_sec: { bike: 7200 }, distance_m: { bike: 60000 } }, planned: { duration_sec: { bike: 7200 }, distance_m: { bike: 60000 } } },
});
const todayStub = {
  header: { today: "2026-09-16", phase: "active", goal: null, week: { start: "2026-09-14", number: null, of: null }, last_sync: [] },
  session: null, readiness: null, fuel: { target: null, targets_through: null }, week: null,
  labs: null, labs_enabled: false, labs_missing: false,
  verdict: { level: "none", reasons: [], based_on: null, stale: false, harder_than_call: false, session_done: false },
  conditions: [], pending: null,
};

async function stub(page: Page, asked: string[] = []) {
  await page.route("**/api/today", (r) => r.fulfill({ json: todayStub }));
  await page.route("**/api/system/status", (r) => r.fulfill({ json: { live: false, tools: [], ready: { api_key: true, checkpointer: true, store: true }, thread: "coach", running: null } }));
  await page.route("**/api/progress**", (r) => {
    const range = new URL(r.request().url()).searchParams.get("range") ?? "";
    asked.push(range);
    return r.fulfill({ json: progress(range) });
  });
}

test("Progress renders every chart and the range picker changes the request", async ({ page }) => {
  const asked: string[] = [];
  await stub(page, asked);
  await page.goto("/progress");
  for (const h of ["Performance management", "Fitness ramp rate", "Weekly volume by sport", "Longest workout by week", "Sport share"]) {
    await expect(page.getByRole("heading", { name: h })).toBeVisible();
  }
  await page.locator("label", { hasText: "6 weeks" }).click();
  await expect.poll(() => asked.at(-1)).toBe("6w");
  await expect(page).toHaveURL(/range=6w/);
  await page.getByRole("button", { name: "View as table" }).first().click();
  await expect(page.getByRole("table").first()).toBeVisible();
});

test("the day slider steps with the arrow keys", async ({ page }) => {
  await stub(page);
  await page.goto("/progress");
  const readout = page.getByTestId("pmc-readout");
  await expect(readout).toContainText("CTL 40.0");
  await page.getByRole("slider", { name: "Inspect day" }).focus();
  await page.keyboard.press("ArrowLeft");
  await expect(readout).toContainText("CTL 39.0");
});

test("Progress fits a phone with no horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await stub(page);
  await page.goto("/progress");
  await expect(page.getByRole("heading", { name: "Sport share" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});
