// useLiveJob's real code, driven by a minimal synchronous hooks runtime (B1-FIX3 A4).
//
// The project has no React test renderer, so "react" is replaced with just enough
// of it: state, refs, callbacks and effects with dependency checks. Realtime is
// blocked (the client cannot even be constructed), so only polling can deliver.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const runtime = vi.hoisted(() => {
  type Effect = { deps: unknown[] | undefined; cleanup?: (() => void) | void };
  const slots: unknown[] = [];
  const effects: Effect[] = [];
  const pending: Array<() => void> = [];
  let cursor = 0;
  let effectCursor = 0;
  let renderFn: (() => unknown) | null = null;
  let scheduled = false;
  let result: unknown;

  const same = (a: unknown[] | undefined, b: unknown[] | undefined) =>
    a !== undefined && b !== undefined && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));

  function render(): void {
    if (!renderFn) return;
    cursor = 0;
    effectCursor = 0;
    result = renderFn();
    const run = pending.splice(0);
    for (const effect of run) effect();
  }

  function rerenderSoon(): void {
    if (scheduled) return;
    scheduled = true;
    void Promise.resolve().then(() => {
      scheduled = false;
      render();
    });
  }

  const react = {
    useState<T>(initial: T) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      const set = (next: T | ((prev: T) => T)) => {
        const value =
          typeof next === "function" ? (next as (prev: T) => T)(slots[index] as T) : next;
        if (!Object.is(value, slots[index])) {
          slots[index] = value;
          rerenderSoon();
        }
      };
      return [slots[index] as T, set] as const;
    },
    useRef<T>(initial: T) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { current: initial };
      return slots[index] as { current: T };
    },
    useCallback<T>(fn: T, deps: unknown[]) {
      const index = cursor++;
      const prev = slots[index] as { fn: T; deps: unknown[] } | undefined;
      if (prev && same(prev.deps, deps)) return prev.fn;
      slots[index] = { fn, deps };
      return fn;
    },
    useEffect(fn: () => (() => void) | void, deps?: unknown[]) {
      const index = effectCursor++;
      const prev = effects[index];
      if (prev && same(prev.deps, deps)) return;
      pending.push(() => {
        if (prev?.cleanup) prev.cleanup();
        effects[index] = { deps, cleanup: fn() };
      });
      if (!prev) effects[index] = { deps: undefined };
    },
  };

  return {
    react,
    mount(fn: () => unknown) {
      renderFn = fn;
      render();
    },
    rerender: render,
    get result() {
      return result;
    },
    unmount() {
      for (const effect of effects) if (effect?.cleanup) effect.cleanup();
      slots.length = 0;
      effects.length = 0;
      renderFn = null;
    },
  };
});

vi.mock("react", () => runtime.react);
vi.mock("./supabase", () => ({
  createRlsClient: () => {
    throw new Error("Realtime is blocked in this test");
  },
}));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getLatestJob: vi.fn(),
}));

import { ApiError, type JobView, getLatestJob } from "./api";
import { useLiveJob } from "./use-live-job";

function job(over: Partial<JobView> = {}): JobView {
  return {
    id: "j1",
    project_id: "p1",
    job_type: "presentation_generation",
    status: "completed",
    progress: { step: "done" },
    error_message: null,
    existing: false,
    created_at: null,
    started_at: null,
    heartbeat_at: null,
    completed_at: null,
    package: null,
    deducted_amount: null,
    refunded: false,
    render_job_id: "r1",
    render_status: "completed",
    render_progress: { step: "done" },
    ...over,
  };
}

const latest = vi.mocked(getLatestJob);
const session = { accessToken: "t", expiresAt: 0, userId: "u" };
// Stable across renders, as the page's withAuth is.
const withAuth = <T,>(call: (token: string) => Promise<T>): Promise<T | null> => call("t");

function mount(onDeckChanged: () => void, hasDeck: boolean): void {
  runtime.mount(() =>
    useLiveJob({
      projectId: "p1",
      session: session as never,
      withAuth,
      onDeckChanged,
      hasDeck,
    }),
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  (globalThis as { window?: unknown }).window = globalThis;
  latest.mockReset();
});

afterEach(() => {
  runtime.unmount();
  vi.useRealTimers();
});

describe("useLiveJob without Realtime (B1-FIX3 A4)", () => {
  it("refreshes the deck when the first job it sees has already finished", async () => {
    // No job when the page opens; the next poll finds one created, rendered and
    // delivered entirely in between.
    latest.mockRejectedValueOnce(new ApiError(404, "job_not_found")).mockResolvedValue(job());
    const onDeckChanged = vi.fn();
    mount(onDeckChanged, true);
    await vi.advanceTimersByTimeAsync(0);
    expect(onDeckChanged).not.toHaveBeenCalled();

    // The "no job yet" answer backs the poll off to 4.5 s.
    await vi.advanceTimersByTimeAsync(4_500);

    expect(latest).toHaveBeenCalledTimes(2);
    expect(onDeckChanged, "a job first seen finished never refreshed the deck").toHaveBeenCalledTimes(1);
    // The same finished job on later polls is not a change: no extra refreshes.
    await vi.advanceTimersByTimeAsync(60_000);
    expect(onDeckChanged).toHaveBeenCalledTimes(1);
  });

  it("keeps re-reading a missing deck while the job says one exists, without any fingerprint change", async () => {
    latest.mockResolvedValue(job());
    const onDeckChanged = vi.fn();
    mount(onDeckChanged, false);
    await vi.advanceTimersByTimeAsync(0);
    const afterFirstSight = onDeckChanged.mock.calls.length;

    // 3 s, 4.5 s, 6.75 s: three retries of the deck within 15 s.
    await vi.advanceTimersByTimeAsync(15_000);

    expect(
      onDeckChanged.mock.calls.length - afterFirstSight,
      "the missing deck was never asked for again",
    ).toBeGreaterThanOrEqual(3);
    // Once the deck is there the retry stops.
    runtime.mount(() =>
      useLiveJob({
        projectId: "p1",
        session: session as never,
        withAuth,
        onDeckChanged,
        hasDeck: true,
      }),
    );
    const settled = onDeckChanged.mock.calls.length;
    await vi.advanceTimersByTimeAsync(120_000);
    expect(onDeckChanged.mock.calls.length).toBe(settled);
  });
});
