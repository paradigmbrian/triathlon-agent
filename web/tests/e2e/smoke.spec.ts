import { expect, test, type Page } from "@playwright/test";

const today = {
  header: { today: "2026-09-16", phase: "active", goal: { goal_type: "olympic", event_name: "City Tri", event_date: "2026-11-01", days_to_go: 46 }, week: { start: "2026-09-14", number: 1, of: 3 }, last_sync: [] },
  session: { workouts: [{ tp_workout_id: "w1", sport: "run", title: "Tempo", completed: false, planned_duration_sec: 3600, planned_tss: 60, actual_duration_sec: null, actual_tss: null }], fuel: null },
  readiness: null,
  fuel: { target: null, targets_through: null },
  week: { phase: "build", target_hours: 6, target_tss: 300, actual_hours: 1, actual_tss: 60, sessions: [] },
  labs: null, labs_enabled: false, labs_missing: false, pending: null,
};
const proposal = { id: "p1", domain: "planning", summary: "move it", changes: [{ op: "move", workout_date: null, tp_workout_id: "w1", workout: null, new_date: "2026-09-18", payload: null, reason: "knee", athlete_requested: false }], violations: [], question: null, overrides: null };
const interrupt = { narration: "Knee: move Wednesday to Friday.", proposals: [proposal] };

function sse(frames: [string, unknown][]) {
  return frames.map(([n, d]) => `event: ${n}\ndata: ${JSON.stringify(d)}\n\n`).join("");
}

async function stub(page: Page) {
  let thread: Record<string, unknown> = { messages: [], paused: null, held: null, stuck: false, running: null };
  await page.route("**/api/today", (r) => r.fulfill({ json: today }));
  await page.route("**/api/system/status", (r) => r.fulfill({ json: { live: false, tools: [], ready: { api_key: true, checkpointer: true, store: true }, thread: "coach", running: null } }));
  await page.route("**/api/coach/thread", (r) => r.fulfill({ json: thread }));
  await page.route("**/api/coach/review/schema", (r) => r.fulfill({ json: { proposal: {}, planning_change: { type: "object", properties: {} }, nutrition_change: { type: "object", properties: {} } } }));
  await page.route("**/api/coach/turns", async (r) => {
    thread = {
      messages: [
        { id: "h1", role: "user", text: "move my Wednesday run" },
        { id: "a1", role: "assistant", where: "coach", text: "Planning suggests Friday." },
      ],
      paused: interrupt, held: null, stuck: false, running: null,
    };
    await r.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: sse([
        ["token", { where: "coach", text: "Planning " }],
        ["token", { where: "coach", text: "suggests Friday." }],
        ["interrupt", interrupt],
        ["done", { final_text: "Planning suggests Friday.", paused: true }],
      ]),
    });
  });
  await page.route("**/api/coach/review", async (r) => {
    thread = { messages: [...(thread.messages as unknown[]), { id: "r1", role: "report", text: "planning: applied 1" }], paused: null, held: null, stuck: false, running: null };
    await r.fulfill({ status: 200, contentType: "text/event-stream", body: sse([["report", { text: "planning: applied 1" }], ["done", { final_text: "planning: applied 1", paused: false }]]) });
  });
}

test("load Today, send a message, see tokens, see a gate, approve, see a report", async ({ page }) => {
  await stub(page);
  await page.goto("/");
  await expect(page.getByText("Tempo")).toBeVisible();
  await expect(page.getByText(/46 days to City Tri/)).toBeVisible();
  await page.getByLabel("Message").fill("move my Wednesday run");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Planning suggests Friday.")).toBeVisible();
  const gate = page.getByRole("region", { name: "Review" });
  await expect(gate).toBeVisible();
  await expect(gate.getByText("Knee: move Wednesday to Friday.")).toBeVisible();
  await expect(gate.getByText(/move w1 to/)).toBeVisible();
  await expect(page.getByText("1 review pending")).toHaveCount(0); // today.pending is null in the stub
  await gate.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("planning: applied 1")).toBeVisible();
  await expect(page.getByRole("region", { name: "Review" })).toHaveCount(0);
});

test("the page works at phone width", async ({ page }) => {
  await stub(page);
  await page.setViewportSize({ width: 400, height: 800 });
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Settings" })).toBeVisible();
  const box = await page.getByRole("navigation", { name: "Sections" }).boundingBox();
  expect(box && box.y > 600).toBeTruthy(); // the rail is a bottom bar
  await expect(page.getByLabel("Message")).toBeVisible();
});
