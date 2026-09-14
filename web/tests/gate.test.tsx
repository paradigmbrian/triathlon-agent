import { fireEvent, screen, waitFor } from "@testing-library/react";
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
