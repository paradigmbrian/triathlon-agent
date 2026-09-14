import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { render } from "@testing-library/react";
import type { ReviewPayload, SchemaOut, ThreadView, TodayView } from "../src/api/queries";

export function todayEmpty(): TodayView {
  return {
    header: { today: "2026-09-16", phase: "intake", goal: null, week: { start: "2026-09-14", number: null, of: null }, last_sync: [] },
    session: null,
    readiness: null,
    fuel: { target: null, targets_through: null },
    week: null,
    labs: null,
    labs_enabled: false,
    labs_missing: false,
    pending: null,
  };
}

export function todayFull(): TodayView {
  return {
    ...todayEmpty(),
    header: {
      today: "2026-09-16",
      phase: "active",
      goal: { goal_type: "olympic", event_name: "City Tri", event_date: "2026-11-01", days_to_go: 46 },
      week: { start: "2026-09-14", number: 1, of: 3 },
      last_sync: [{ source: "garmin", last_synced_date: "2026-09-16", last_run_at: "2026-09-16T06:10:00Z", status: "ok", error: null }],
    },
    session: {
      workouts: [{ tp_workout_id: "w1", sport: "run", title: "Tempo", completed: false, planned_duration_sec: 3600, planned_tss: 60, actual_duration_sec: null, actual_tss: null }],
      fuel: { id: 1, kind: "session", tp_workout_id: "w1", payload: { carbs_g_per_h: 60, pre: "toast" }, violations: [], written: false },
    },
    readiness: { date: "2026-09-16", is_today: true, sleep_score: 81, sleep_hours: 7.5, hrv: 62, resting_hr: 48, body_battery: 92, training_readiness: 77, ctl: 45.2, atl: 50.1, tsb: -4.9 },
    fuel: { target: { day_type: "moderate", total_kcal: 2900, carbs_g: 380, protein_g: 150, fat_g: 80, fluid_baseline_ml: 2500, written_to_garmin: false }, targets_through: "2026-09-20" },
    week: { phase: "build", target_hours: 6, target_tss: 300, actual_hours: 2.5, actual_tss: 120, sessions: [{ sport: "run", planned: 2, completed: 1 }, { sport: "bike", planned: 2, completed: 1 }] },
  };
}

export function threadEmpty(): ThreadView {
  return { messages: [], paused: null, held: null, stuck: false, running: null };
}

export function paused(): ReviewPayload {
  return {
    narration: "Knee: move Wednesday.",
    proposals: [
      {
        id: "p1",
        domain: "planning",
        summary: "move it",
        changes: [{ op: "move", workout_date: null, tp_workout_id: "w1", workout: null, new_date: "2026-09-18", payload: null, reason: "knee", athlete_requested: false }],
        violations: [],
        question: null,
        overrides: null,
      },
    ],
  };
}

export function schema(): SchemaOut {
  return {
    proposal: { type: "object", properties: { id: { type: "string" }, domain: { enum: ["planning", "nutrition"], type: "string" }, summary: { type: "string" } } },
    planning_change: {
      $defs: {
        PlannedSession: {
          type: "object",
          properties: {
            date: { type: "string", format: "date" },
            sport: { enum: ["swim", "bike", "run", "brick", "strength", "rest"], type: "string" },
            title: { type: "string" },
            description: { type: "string" },
            duration_minutes: { type: "integer", minimum: 0 },
            tss_planned: { type: "number", minimum: 0 },
            intensity: { enum: ["recovery", "endurance", "tempo", "threshold", "vo2", "race"], type: "string" },
            structure: { anyOf: [{ type: "object", additionalProperties: true }, { type: "null" }], default: null },
          },
          required: ["date", "sport", "title", "description", "duration_minutes", "tss_planned", "intensity"],
        },
      },
      type: "object",
      properties: {
        op: { enum: ["create", "update", "delete", "move", "apply_plan", "create_event"], type: "string" },
        workout_date: { anyOf: [{ type: "string", format: "date" }, { type: "null" }], default: null },
        tp_workout_id: { anyOf: [{ type: "string" }, { type: "null" }], default: null },
        workout: { anyOf: [{ $ref: "#/$defs/PlannedSession" }, { type: "null" }], default: null },
        new_date: { anyOf: [{ type: "string", format: "date" }, { type: "null" }], default: null },
        payload: { anyOf: [{ type: "object", additionalProperties: true }, { type: "null" }], default: null },
        reason: { type: "string" },
        athlete_requested: { type: "boolean", default: false },
      },
      required: ["op", "reason"],
    },
    nutrition_change: {
      type: "object",
      properties: {
        op: { enum: ["set_day_targets", "set_session_note", "set_race_note"], type: "string" },
        target_key: { type: "string" },
        day: { type: "string", format: "date" },
        payload: { type: "object", additionalProperties: true },
        reason: { type: "string" },
      },
      required: ["op", "target_key", "day", "payload", "reason"],
    },
  };
}

export function renderWith(ui: ReactElement, { route = "/" }: { route?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}
