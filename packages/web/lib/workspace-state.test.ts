import { describe, expect, it } from "vitest";
import type { JobView } from "./api";
import {
  deriveWorkspaceState,
  elapsedMs,
  formatElapsed,
  isRunning,
  isStalled,
  STALL_AFTER_MS,
  startedAtMs,
} from "./workspace-state";

function job(overrides: Partial<JobView> = {}): JobView {
  return {
    id: "job-1",
    project_id: "proj-1",
    job_type: "presentation_generation",
    status: "processing",
    progress: {},
    error_message: null,
    existing: false,
    created_at: "2026-08-23T10:00:00Z",
    started_at: "2026-08-23T10:00:30Z",
    heartbeat_at: "2026-08-23T10:01:00Z",
    completed_at: null,
    package: "presentation_standard",
    deducted_amount: 10_000,
    refunded: false,
    ...overrides,
  };
}

const presentation = { status: "ready", project_type: "presentation" };

describe("deriveWorkspaceState — the enqueue CTA", () => {
  // The audit's G3/G5: an idle priced button rendered over a running, failed or
  // delivered project, where the click was a real second charge.
  it("is the ONLY thing that can offer a first paid run, and only with no job", () => {
    const state = deriveWorkspaceState(presentation, null, false, true);
    expect(state.kind).toBe("no_job");
    expect(state.canEnqueue).toBe(true);
    expect(state.enqueueIsRepeat).toBe(false);
  });

  it("never offers to enqueue while a job is queued or processing", () => {
    for (const status of ["queued", "processing"]) {
      const state = deriveWorkspaceState(presentation, job({ status }), false, true);
      expect(state.kind).toBe(status);
      expect(state.canEnqueue).toBe(false);
    }
  });

  it("offers a REPEAT (never the idle pitch) on a failed project", () => {
    const state = deriveWorkspaceState(presentation, job({ status: "failed" }), false, true);
    expect(state.kind).toBe("failed");
    expect(state.canEnqueue).toBe(true);
    expect(state.enqueueIsRepeat).toBe(true);
  });

  it("offers a REPEAT on a delivered project", () => {
    const state = deriveWorkspaceState(presentation, job({ status: "completed" }), true, true);
    expect(state.kind).toBe("ready");
    expect(state.enqueueIsRepeat).toBe(true);
  });

  it("waits rather than selling when the job completed but no deck landed", () => {
    const state = deriveWorkspaceState(presentation, job({ status: "completed" }), false, true);
    expect(state.kind).toBe("completed_no_deck");
    expect(state.canEnqueue).toBe(false);
  });
});

describe("deriveWorkspaceState — non-presentation and archived", () => {
  it("routes an article project away from every presentation state", () => {
    const state = deriveWorkspaceState(
      { status: "sourcing", project_type: "article" },
      null,
      false,
      true,
    );
    expect(state.kind).toBe("article_project");
    expect(state.canEnqueue).toBe(false);
  });

  it("keeps an archived project read-only even with no job", () => {
    const state = deriveWorkspaceState(
      { status: "archived", project_type: "presentation" },
      null,
      false,
      true,
    );
    expect(state.kind).toBe("archived");
    expect(state.canEnqueue).toBe(false);
  });

  it("holds a skeleton until the job lookup has actually settled", () => {
    // Otherwise the page flashes `no_job` — the priced button — for one frame
    // over a project that turns out to be mid-run.
    expect(deriveWorkspaceState(presentation, null, false, false).kind).toBe("loading");
    expect(deriveWorkspaceState(null, null, false, true).kind).toBe("loading");
  });

  it("treats a missing project_type as a presentation (pre-column rows)", () => {
    expect(deriveWorkspaceState({ status: "draft" }, null, false, true).kind).toBe("no_job");
  });
});

describe("isRunning", () => {
  it("counts only queued and processing", () => {
    expect(isRunning(job({ status: "queued" }))).toBe(true);
    expect(isRunning(job({ status: "processing" }))).toBe(true);
    expect(isRunning(job({ status: "completed" }))).toBe(false);
    expect(isRunning(job({ status: "failed" }))).toBe(false);
    expect(isRunning(null)).toBe(false);
  });
});

describe("elapsed time", () => {
  it("measures from started_at, falling back to created_at for a queued job", () => {
    const now = new Date("2026-08-23T10:02:00Z").getTime();
    expect(elapsedMs(job(), now)).toBe(90_000);
    expect(elapsedMs(job({ started_at: null }), now)).toBe(120_000);
  });

  it("freezes at completion instead of ticking forever", () => {
    const finished = job({ status: "completed", completed_at: "2026-08-23T10:01:30Z" });
    const now = new Date("2026-08-23T11:00:00Z").getTime();
    expect(elapsedMs(finished, now)).toBe(60_000);
  });

  it("returns null when the row carries no usable timestamp", () => {
    expect(elapsedMs(job({ started_at: null, created_at: null }))).toBeNull();
    expect(elapsedMs(null)).toBeNull();
    expect(startedAtMs(job({ started_at: null, created_at: null }))).toBeUndefined();
  });

  it("formats without a leading zero minute", () => {
    expect(formatElapsed(9_000)).toBe("9s");
    expect(formatElapsed(90_000)).toBe("1m 30s");
    expect(formatElapsed(605_000)).toBe("10m 05s");
  });
});

describe("isStalled", () => {
  const beat = new Date("2026-08-23T10:01:00Z").getTime();

  it("stays quiet while the heartbeat is fresh", () => {
    expect(isStalled(job(), beat + STALL_AFTER_MS - 1_000)).toBe(false);
  });

  it("reports a stall once three heartbeats have been missed", () => {
    expect(isStalled(job(), beat + STALL_AFTER_MS + 1_000)).toBe(true);
  });

  it("never claims a stall for a job that is not processing", () => {
    // A completed job's heartbeat is by definition old; calling that a stall
    // would put a scary banner over every delivered deck.
    for (const status of ["queued", "completed", "failed"]) {
      expect(isStalled(job({ status }), beat + 10 * STALL_AFTER_MS)).toBe(false);
    }
  });

  it("cannot stall on a row that never beat", () => {
    expect(isStalled(job({ heartbeat_at: null }), beat + 10 * STALL_AFTER_MS)).toBe(false);
  });
});
