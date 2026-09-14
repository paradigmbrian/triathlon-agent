import { api, ApiError } from "../src/api/client";

afterEach(() => vi.restoreAllMocks());

test("ApiError takes a string detail as its message and falls back to the status otherwise", () => {
  expect(new ApiError(409, { detail: "a turn is running" }).message).toBe("a turn is running");
  expect(new ApiError(422, { detail: [{ loc: ["body", "text"], msg: "field required", type: "missing" }] }).message).toBe("HTTP 422");
  expect(new ApiError(422, { detail: { msg: "nested" } }).message).toBe("HTTP 422");
  expect(new ApiError(500, null).message).toBe("HTTP 500");
  expect(new ApiError(502, "Bad Gateway").message).toBe("HTTP 502");
});

test("api() rejects a list-shaped detail with the status, keeping the body", async () => {
  const detail = [{ loc: ["body", "text"], msg: "field required", type: "missing" }];
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail }), { status: 422 }));
  await expect(api("/api/coach/turns")).rejects.toMatchObject({ status: 422, message: "HTTP 422", body: { detail } });
});
