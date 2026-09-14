import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Settings from "../src/pages/Settings";
import { renderWith } from "./fixtures";

const memory = { entries: [{ id: "a1b2c3", kind: "injury", text: "left knee", created: "2026-09-01", until: "2026-09-30" }], active_ids: ["a1b2c3"] };
const status = { live: false, tools: [], ready: { api_key: true, checkpointer: true, store: false }, thread: "coach", running: null };

function mockApi() {
  const f = vi.spyOn(globalThis, "fetch");
  f.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "/api/coach/memory" && (!init || init.method === undefined)) return new Response(JSON.stringify(memory), { status: 200 });
    if (url.startsWith("/api/coach/memory/") && init?.method === "DELETE") return new Response(null, { status: 204 });
    if (url === "/api/system/status") return new Response(JSON.stringify(status), { status: 200 });
    if (url === "/api/coach/reset") return new Response(null, { status: 204 });
    return new Response("nope", { status: 404 });
  });
  return f;
}

afterEach(() => vi.restoreAllMocks());

test("memory rows, forget, readiness checks and the reset dialog", async () => {
  const f = mockApi();
  const user = userEvent.setup();
  renderWith(<Settings />);
  await screen.findByText("left knee");
  expect(screen.getByText("injury")).toBeInTheDocument();
  expect(screen.getByText("active")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "forget a1b2c3" }));
  await waitFor(() => expect(f).toHaveBeenCalledWith("/api/coach/memory/a1b2c3", expect.objectContaining({ method: "DELETE" })));
  expect(await screen.findByText(/store tables/)).toHaveClass("text-danger");
  expect(screen.getByText(/API key/)).toHaveClass("text-accent");
  expect(screen.getByText(/live tools: none/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Reset conversation" }));
  await user.click(screen.getByLabelText("forget memory too"));
  await user.click(screen.getByRole("button", { name: "Confirm reset" }));
  await waitFor(() =>
    expect(f).toHaveBeenCalledWith("/api/coach/reset", expect.objectContaining({ method: "POST", body: JSON.stringify({ confirm: true, forget_memory: true }) })),
  );
});
