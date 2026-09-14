import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SchemaForm from "../src/components/gate/SchemaForm";
import { describeChange, fieldsOf } from "../src/components/gate/schemaUtils";
import { paused, renderWith, schema } from "./fixtures";

test("fieldsOf resolves refs, nullable anyOf, enums, dates and dicts", () => {
  const s = schema();
  const fields = fieldsOf(s.planning_change, s.planning_change);
  const by = Object.fromEntries(fields.map((f) => [f.name, f]));
  expect(by.op.kind).toBe("enum");
  expect(by.op.enum).toContain("move");
  expect(by.new_date.kind).toBe("date");
  expect(by.new_date.required).toBe(false);
  expect(by.workout.kind).toBe("object");
  expect(by.workout.nested?.map((f) => f.name)).toContain("duration_minutes");
  expect(by.workout.nested?.find((f) => f.name === "duration_minutes")?.kind).toBe("number");
  expect(by.payload.kind).toBe("dict");
  expect(by.athlete_requested.kind).toBe("boolean");
  expect(by.reason.required).toBe(true);
});

test("describeChange gives one line per op", () => {
  expect(describeChange("planning", { op: "move", tp_workout_id: "w1", new_date: "2026-09-18" })).toBe("move w1 to Fri, Sep 18");
  expect(
    describeChange("planning", { op: "create", workout_date: "2026-09-19", workout: { sport: "run", duration_minutes: 60, description: "easy" } }),
  ).toBe("create Sat, Sep 19: run 60 min, easy");
  expect(describeChange("nutrition", { op: "set_day_targets", day: "2026-09-14", target_key: "2026-09-14", payload: { calorie_goal: 2800 } })).toBe(
    "set_day_targets Mon, Sep 14: calorie_goal=2800",
  );
});

test("the form renders each field type, edits a date, removes a change, emits JSON", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  renderWith(<SchemaForm schema={schema()} proposal={paused().proposals[0]} errors={{}} onChange={onChange} onRemove={() => {}} canRemove />);
  expect(screen.getByLabelText("summary")).toHaveValue("move it");
  expect(screen.getByText("p1")).toBeInTheDocument(); // id is read-only text
  const op = screen.getByLabelText("op") as HTMLSelectElement;
  expect(op.tagName).toBe("SELECT");
  expect(op.value).toBe("move");
  const date = screen.getByLabelText("new_date") as HTMLInputElement;
  expect(date.type).toBe("date");
  fireEvent.change(date, { target: { value: "2026-09-19" } });
  expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ changes: [expect.objectContaining({ new_date: "2026-09-19" })] }));
  expect(screen.getByLabelText("athlete_requested")).toHaveAttribute("type", "checkbox");
  await user.click(screen.getByRole("button", { name: "remove change 1" }));
  expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ changes: [] }));
});

test("errors show under their field by loc path", () => {
  renderWith(
    <SchemaForm schema={schema()} proposal={paused().proposals[0]} errors={{ "changes.0.new_date": "bad date" }} onChange={() => {}} onRemove={() => {}} canRemove={false} />,
  );
  expect(screen.getByText("bad date")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "remove proposal" })).not.toBeInTheDocument();
});
