import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { describeError } from "./errors";
import {
  applyJob,
  chipOf,
  elapsedLabel,
  isNewerJob,
  jobSnapshot,
  liveStatusOf,
  newestByProject,
  stepLabelOf,
  supabaseFailure,
  type JobSnapshot,
} from "./folio";

function job(over: Partial<JobSnapshot> = {}): JobSnapshot {
  return {
    id: "j1",
    projectId: "p1",
    status: "processing",
    progress: { step: "Choosing design direction", current: 4, total: 7 },
    createdAt: "2026-08-23T10:00:00Z",
    startedAt: "2026-08-23T10:00:05Z",
    ...over,
  };
}

// G12: supabase-js resolves — it does not throw — when the network is dead, so
// the fix is the mapping, not the .catch. Every branch here is a state the
// folio previously rendered as an eternal skeleton.
describe("supabaseFailure gives an unreachable backend human copy", () => {
  it("maps a request that never reached the server to the offline copy", () => {
    const friendly = describeError(supabaseFailure({ message: "TypeError: fetch failed" }, 0));
    expect(friendly.title).toBe("Internet uzildi");
    expect(friendly.action?.kind).toBe("retry");
  });

  it("maps an aborted (timed-out) read to the timeout copy", () => {
    const friendly = describeError(
      supabaseFailure({ message: "AbortError: The user aborted a request.", code: "" }, 0),
    );
    expect(friendly.reason).toBe("timeout");
    expect(friendly.action?.kind).toBe("retry");
  });

  it("honours an explicit ABORT_ERR code even when the message does not say so", () => {
    const mapped = supabaseFailure({ message: "The operation was aborted", code: "ABORT_ERR" }, 0);
    expect(describeError(mapped).reason).toBe("timeout");
  });

  it("maps a server-side PostgREST failure by status, never by its raw sentence", () => {
    const friendly = describeError(
      supabaseFailure(
        { message: "JSON object requested, multiple (or no) rows returned", code: "PGRST116" },
        500,
      ),
    );
    expect(friendly.title).toBe("Xizmatda nosozlik");
    expect(friendly.message).not.toContain("PGRST116");
    // The machine text survives, but only inside the collapsible detail.
    expect(friendly.detail).toContain("PGRST116");
  });

  it("never lets a raw code become the reason a surface branches on", () => {
    const mapped = supabaseFailure({ message: "permission denied", code: "42501" }, 403);
    expect(mapped).toBeInstanceOf(ApiError);
    expect(describeError(mapped).reason).toBeNull();
    expect(describeError(mapped).title).toBe("Ruxsat yo‘q");
  });

  it("produces human copy for a shapeless failure", () => {
    const friendly = describeError(supabaseFailure(null, 0));
    expect(friendly.title.length).toBeGreaterThan(0);
    expect(friendly.message.length).toBeGreaterThan(0);
  });
});

// G25: rows carried a chip and nothing else.
describe("jobSnapshot maps rows and Realtime records alike", () => {
  it("reads a generation_jobs row", () => {
    const snapshot = jobSnapshot({
      id: "j1",
      project_id: "p1",
      status: "processing",
      progress: { step: "Rendering presentation", current: 7, total: 7 },
      created_at: "2026-08-23T10:00:00Z",
      started_at: null,
    });
    expect(snapshot?.projectId).toBe("p1");
    expect(snapshot?.startedAt).toBeNull();
    expect(snapshot?.progress.total).toBe(7);
  });

  it("returns null for anything that is not a job row", () => {
    for (const value of [null, undefined, 42, "row", {}, { id: "j1" }]) {
      expect(jobSnapshot(value)).toBeNull();
    }
  });

  it("tolerates a missing progress object", () => {
    const snapshot = jobSnapshot({ id: "j1", project_id: "p1", status: "queued" });
    expect(snapshot?.progress).toEqual({});
  });
});

describe("the live map keeps the run the user is watching", () => {
  it("keeps only the newest active job per project", () => {
    const map = newestByProject([
      { id: "old", project_id: "p1", status: "queued", created_at: "2026-08-23T09:00:00Z" },
      { id: "new", project_id: "p1", status: "processing", created_at: "2026-08-23T10:00:00Z" },
      { id: "done", project_id: "p2", status: "completed", created_at: "2026-08-23T10:00:00Z" },
    ]);
    expect(map.p1?.id).toBe("new");
    expect(map.p2).toBeUndefined();
  });

  it("ignores a replayed event about an older job", () => {
    const held = { p1: job({ id: "new", createdAt: "2026-08-23T10:00:00Z" }) };
    const next = applyJob(held, job({ id: "old", createdAt: "2026-08-23T09:00:00Z" }));
    expect(next).toBe(held);
    expect(isNewerJob(job({ id: "old", createdAt: "2026-08-23T09:00:00Z" }), held.p1)).toBe(false);
  });

  it("accepts a later state of the same run", () => {
    const held = { p1: job({ status: "queued" }) };
    expect(applyJob(held, job({ status: "processing" })).p1?.status).toBe("processing");
  });

  it("drops the entry when the run ends, so the row falls back to the project", () => {
    const held = { p1: job(), p2: job({ id: "j2", projectId: "p2" }) };
    const next = applyJob(held, job({ status: "completed" }));
    expect(next.p1).toBeUndefined();
    expect(next.p2).toBeDefined();
  });

  it("does not churn identity for a terminal event it never tracked", () => {
    const held = {};
    expect(applyJob(held, job({ status: "failed" }))).toBe(held);
  });
});

describe("badge and chip cannot disagree", () => {
  it("lets a live job outrank a projects row the worker has not stamped yet", () => {
    expect(liveStatusOf("draft", job({ status: "processing" }))).toBe("generating");
    expect(liveStatusOf("draft", job({ status: "queued" }))).toBe("queued");
    expect(chipOf(liveStatusOf("draft", job({ status: "queued" })))).toBe("generating");
    expect(chipOf(liveStatusOf("draft", job({ status: "processing" })))).toBe("generating");
  });

  it("falls back to the project row with no live job", () => {
    expect(liveStatusOf("ready", null)).toBe("ready");
    expect(liveStatusOf("ready", job({ status: "completed" }))).toBe("ready");
  });

  it("groups every known status under exactly one chip", () => {
    expect(chipOf("sourcing")).toBe("draft");
    expect(chipOf("cancelled")).toBe("failed");
    expect(chipOf("archived")).toBe("archived");
    expect(chipOf("who_knows")).toBe("other");
  });
});

describe("a generating row says which step it is on", () => {
  it("names the running step with the wire's own denominator", () => {
    expect(stepLabelOf(job())).toBe("4/7 · Dizayn yo'nalishi tanlanmoqda");
  });

  it("stays quiet for a queued job — the badge already says Navbatda", () => {
    expect(stepLabelOf(job({ status: "queued" }))).toBeNull();
    expect(stepLabelOf(null)).toBeNull();
  });

  it("renders an unknown step honestly rather than mislabelling it", () => {
    const label = stepLabelOf(job({ progress: { step: "Polishing", current: 2, total: 3 } }));
    expect(label).toBe("2/3 · Polishing");
  });
});

describe("elapsed time", () => {
  const start = Date.parse("2026-08-23T10:00:00Z");

  it("counts from started_at, falling back to created_at", () => {
    expect(elapsedLabel(job({ startedAt: null }), start + 45_000)).toBe("45 s");
    expect(elapsedLabel(job({ startedAt: "2026-08-23T10:00:00Z" }), start + 45_000)).toBe("45 s");
  });

  it("steps up through minutes and hours", () => {
    const anchored = job({ startedAt: "2026-08-23T10:00:00Z" });
    expect(elapsedLabel(anchored, start + 3 * 60_000)).toBe("3 daq");
    expect(elapsedLabel(anchored, start + 65 * 60_000)).toBe("1 soat 5 daq");
  });

  it("stays silent for a finished job, a clock skew, or a broken timestamp", () => {
    expect(elapsedLabel(job({ status: "completed" }), start + 60_000)).toBeNull();
    expect(elapsedLabel(job({ startedAt: "2026-08-23T10:00:00Z" }), start - 5_000)).toBeNull();
    expect(elapsedLabel(job({ startedAt: "not a date", createdAt: null }), start)).toBeNull();
  });
});
