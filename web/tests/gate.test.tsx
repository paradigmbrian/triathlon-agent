import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "../src/api/client";
import Gate from "../src/components/gate/Gate";
import { paused, renderWith, schema } from "./fixtures";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function stubApi(validate: unknown = { ok: true, proposals: paused().proposals, errors: [] }) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/coach/review/schema") return json(schema());
    if (url === "/api/coach/review/validate") return json(validate);
    if (url === "/api/coach/review/yaml") return json({ yaml: "p1:\n  summary: move it\n" });
    return json({ detail: `unexpected ${url}` }, 500);
  });
}

type Pending = { resolve: (body: unknown) => void; fail: (status: number, body: unknown) => void };

/** Every validate call stays pending until the test resolves it, in whatever order it likes. */
function stubDeferredValidate() {
  const pending: Pending[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url === "/api/coach/review/schema") return Promise.resolve(json(schema()));
    if (url === "/api/coach/review/yaml") return Promise.resolve(json({ yaml: "p1:\n  summary: move it\n" }));
    if (url === "/api/coach/review/validate") {
      return new Promise<Response>((resolve) => {
        // a minimal Response so resolution settles in microtasks alone
        pending.push({
          resolve: (body) => resolve({ ok: true, status: 200, text: async () => JSON.stringify(body) } as unknown as Response),
          fail: (status, body) => resolve({ ok: false, status, text: async () => JSON.stringify(body) } as unknown as Response),
        });
      });
    }
    return Promise.resolve(json({ detail: `unexpected ${url}` }, 500));
  });
  return pending;
}

/** Resolve a pending validate and let every microtask and render it triggers finish. */
async function settle(p: Pending, body: unknown) {
  await act(async () => {
    p.resolve(body);
    await new Promise((r) => setTimeout(r, 0));
  });
}

const dateError = (msg: string) => ({ ok: false, proposals: [], errors: [{ loc: [0, "changes", 0, "new_date"], msg }] });

afterEach(() => vi.restoreAllMocks());

test("a 422 on Send edited shows the server's errors under the matching field and the refusal", async () => {
  stubApi();
  const user = userEvent.setup();
  const onDecide = vi.fn().mockRejectedValue(
    new ApiError(422, {
      detail: "edit rejected",
      errors: [
        { loc: [0, "changes", 0, "new_date"], msg: "bad date" },
        { loc: [0, "changes", 0], msg: "move needs a new_date" },
      ],
    }),
  );
  renderWith(<Gate payload={paused()} mode="paused" onDecide={onDecide} />);
  await user.click(screen.getByRole("button", { name: "Edit" }));
  const date = await screen.findByLabelText("new_date");
  await user.click(screen.getByRole("button", { name: "Send edited" }));
  expect(onDecide).toHaveBeenCalledWith({ action: "edit", proposals: paused().proposals });
  const err = await screen.findByText("bad date");
  expect(date.closest("div")).toContainElement(err);
  expect(screen.getByText("edit rejected")).toBeInTheDocument();
  expect(screen.getByText("changes.0: move needs a new_date")).toBeInTheDocument();
});

test("held mode names why it is held and offers no decisions", async () => {
  stubApi();
  renderWith(<Gate payload={paused()} mode="held" onDecide={vi.fn()} />);
  expect(screen.getByText("held from an earlier apply; ask the coach to re-propose it")).toBeInTheDocument();
  expect(screen.getByText("move it")).toBeInTheDocument();
  for (const name of ["Approve", "Reject", "Edit"]) expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/coach/review/schema", expect.anything()));
});

test("an edit that removes every proposal is refused locally; reject instead", async () => {
  stubApi({ ok: true, proposals: [], errors: [] });
  const user = userEvent.setup();
  const onDecide = vi.fn().mockResolvedValue(undefined);
  renderWith(<Gate payload={paused()} mode="paused" onDecide={onDecide} />);
  await user.click(screen.getByRole("button", { name: "Edit" }));
  await user.click(screen.getByRole("button", { name: "Edit as YAML" }));
  const box = await screen.findByLabelText("YAML");
  fireEvent.change(box, { target: { value: "{}" } });
  const send = screen.getByRole("button", { name: "Send edited" });
  await waitFor(() => expect(send).toBeEnabled());
  await user.click(send);
  expect(await screen.findByText(/reject instead/)).toBeInTheDocument();
  expect(onDecide).not.toHaveBeenCalled();
});

test("YAML mode: changing the text disables Send edited until that text validates", async () => {
  const pending = stubDeferredValidate();
  const user = userEvent.setup();
  renderWith(<Gate payload={paused()} mode="paused" onDecide={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Edit" }));
  await user.click(screen.getByRole("button", { name: "Edit as YAML" }));
  const box = await screen.findByLabelText("YAML");
  const send = screen.getByRole("button", { name: "Send edited" });
  fireEvent.change(box, { target: { value: "p1:\n  summary: first\n" } });
  await waitFor(() => expect(pending).toHaveLength(1));
  await settle(pending[0], { ok: true, proposals: paused().proposals, errors: [] });
  expect(send).toBeEnabled();
  fireEvent.change(box, { target: { value: "p1:\n  summary: second\n" } });
  expect(send).toBeDisabled();
  await waitFor(() => expect(pending).toHaveLength(2));
  expect(send).toBeDisabled();
  await settle(pending[1], { ok: true, proposals: paused().proposals, errors: [] });
  expect(send).toBeEnabled();
});

test("an older validate response landing after a newer one is ignored", async () => {
  const pending = stubDeferredValidate();
  const user = userEvent.setup();
  renderWith(<Gate payload={paused()} mode="paused" onDecide={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Edit" }));
  const date = await screen.findByLabelText("new_date");
  fireEvent.change(date, { target: { value: "2026-09-19" } });
  await waitFor(() => expect(pending).toHaveLength(1));
  fireEvent.change(date, { target: { value: "2026-09-20" } });
  await waitFor(() => expect(pending).toHaveLength(2));
  await settle(pending[1], dateError("newer"));
  expect(screen.getByText("newer")).toBeInTheDocument();
  await settle(pending[0], dateError("older"));
  expect(screen.queryByText("older")).not.toBeInTheDocument();
  expect(screen.getByText("newer")).toBeInTheDocument();
});

test("a validate response landing after a 422 keeps the 422's field errors", async () => {
  const pending = stubDeferredValidate();
  const user = userEvent.setup();
  const onDecide = vi.fn().mockRejectedValue(new ApiError(422, { detail: "edit rejected", ...dateError("bad date") }));
  renderWith(<Gate payload={paused()} mode="paused" onDecide={onDecide} />);
  await user.click(screen.getByRole("button", { name: "Edit" }));
  const date = await screen.findByLabelText("new_date");
  fireEvent.change(date, { target: { value: "2026-09-19" } });
  await waitFor(() => expect(pending).toHaveLength(1));
  await user.click(screen.getByRole("button", { name: "Send edited" }));
  expect(await screen.findByText("bad date")).toBeInTheDocument();
  await settle(pending[0], { ok: true, proposals: paused().proposals, errors: [] });
  expect(screen.getByText("bad date")).toBeInTheDocument();
  expect(screen.getByText("edit rejected")).toBeInTheDocument();
});

test("a validate failure's message clears when a later validate succeeds", async () => {
  const pending = stubDeferredValidate();
  const user = userEvent.setup();
  renderWith(<Gate payload={paused()} mode="paused" onDecide={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Edit" }));
  const date = await screen.findByLabelText("new_date");
  fireEvent.change(date, { target: { value: "2026-09-19" } });
  await waitFor(() => expect(pending).toHaveLength(1));
  await act(async () => {
    pending[0].fail(503, { detail: "validator unavailable" });
    await new Promise((r) => setTimeout(r, 0));
  });
  expect(screen.getByText("validator unavailable")).toBeInTheDocument();
  fireEvent.change(date, { target: { value: "2026-09-20" } });
  await waitFor(() => expect(pending).toHaveLength(2));
  await settle(pending[1], { ok: true, proposals: paused().proposals, errors: [] });
  expect(screen.queryByText("validator unavailable")).not.toBeInTheDocument();
});

test("a 422 whose detail is a list (request validation) still reads edit rejected", async () => {
  stubApi();
  const user = userEvent.setup();
  const onDecide = vi.fn().mockRejectedValue(new ApiError(422, { detail: [{ loc: ["body", "proposals"], msg: "field required", type: "missing" }] }));
  renderWith(<Gate payload={paused()} mode="paused" onDecide={onDecide} />);
  await user.click(screen.getByRole("button", { name: "Edit" }));
  await screen.findByLabelText("new_date");
  await user.click(screen.getByRole("button", { name: "Send edited" }));
  expect(await screen.findByText("edit rejected")).toBeInTheDocument();
});

test("a change row names its op once", async () => {
  stubApi();
  renderWith(<Gate payload={paused()} mode="held" onDecide={vi.fn()} />);
  expect(screen.getByRole("listitem")).toHaveTextContent(/^move w1 to Fri, Sep 18 — knee$/);
  await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/coach/review/schema", expect.anything()));
});

test("two proposals in form mode have unique ids and each label binds inside its own proposal", async () => {
  stubApi();
  const user = userEvent.setup();
  const base = paused();
  const second = { ...base.proposals[0], id: "p2", summary: "other one", changes: [{ ...base.proposals[0].changes[0], reason: "other reason" }] };
  renderWith(<Gate payload={{ ...base, proposals: [base.proposals[0], second] }} mode="paused" onDecide={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Edit" }));
  const p2 = await screen.findByRole("group", { name: "proposal p2" });
  const ids = Array.from(document.querySelectorAll("[id]"), (el) => el.id);
  expect(new Set(ids).size).toBe(ids.length);
  expect(within(p2).getByLabelText("reason")).toHaveValue("other reason");
  expect(within(screen.getByRole("group", { name: "proposal p1" })).getByLabelText("reason")).toHaveValue("knee");
});
