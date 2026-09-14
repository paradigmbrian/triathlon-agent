import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { components } from "./types";

type S = components["schemas"];

// Hand-written: the server's OpenAPI types each proposal as an untyped dict
// ({ [key: string]: unknown }), so openapi-typescript can't produce this shape.
export type ProposalJson = {
  id: string;
  domain: "planning" | "nutrition";
  summary: string;
  changes: Record<string, unknown>[];
  violations: string[];
  question: string | null;
  overrides: Record<string, unknown> | null;
};

export type ReviewPayload = Omit<S["ReviewPayload"], "proposals"> & { proposals: ProposalJson[] };
export type ThreadView = Omit<S["ThreadView"], "paused" | "held"> & {
  paused: ReviewPayload | null;
  held: ReviewPayload | null;
};
export type TodayView = Omit<S["TodayView"], "pending"> & { pending?: ReviewPayload | null };

export type UiMessage = S["UiMessage"];
export type MemoryOut = S["MemoryOut"];
export type MemoryEntry = S["MemoryEntry"];
export type StatusOut = S["StatusOut"];
export type SchemaOut = S["SchemaOut"];
export type Validated = S["Validated"];
export type ValidationItem = S["ValidationItem"];
export type JobOut = S["JobOut"];

export const keys = {
  today: ["today"] as const,
  thread: ["thread"] as const,
  memory: ["memory"] as const,
  status: ["status"] as const,
  schema: ["schema"] as const,
};

export const useToday = () => useQuery({ queryKey: keys.today, queryFn: () => api<TodayView>("/api/today") });
export const useThread = (refetchInterval?: number | false) =>
  useQuery({ queryKey: keys.thread, queryFn: () => api<ThreadView>("/api/coach/thread"), refetchInterval });
export const useMemory = () => useQuery({ queryKey: keys.memory, queryFn: () => api<MemoryOut>("/api/coach/memory") });
export const useStatus = () => useQuery({ queryKey: keys.status, queryFn: () => api<StatusOut>("/api/system/status") });
export const useSchema = () =>
  useQuery({ queryKey: keys.schema, queryFn: () => api<SchemaOut>("/api/coach/review/schema"), staleTime: Infinity });
