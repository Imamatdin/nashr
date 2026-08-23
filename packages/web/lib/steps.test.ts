import { describe, expect, it } from "vitest";
import { STEP_LABELS, stepStates } from "./steps";

describe("stepStates honours the wire, not a hardcoded seven", () => {
  // G39: the list was pinned at seven rows with a literal `n/7` meta, so a job
  // reporting a different total was rendered as a lie.
  it("uses progress.total for both the row count and the meta", () => {
    const rows = stepStates({ step: "Processing sources", current: 1, total: 3 }, "processing");
    expect(rows).toHaveLength(3);
    expect(rows.map((r) => r.meta)).toEqual(["1/3", "2/3", "3/3"]);
  });

  it("falls back to the known label list when the job sends no total", () => {
    expect(stepStates({ current: 1 }, "processing")).toHaveLength(STEP_LABELS.length);
  });

  it("never produces zero rows for a nonsense total", () => {
    expect(stepStates({ total: 0 }, "processing").length).toBeGreaterThan(0);
  });
});

describe("an unknown step name does not mis-highlight", () => {
  it("keeps the active row at `current` instead of guessing from the name", () => {
    // The old code did findIndex(name) and fell through to current only when the
    // lookup failed — but it then rendered THAT index's label, claiming the
    // pipeline was somewhere it was not.
    const rows = stepStates({ step: "Polishing the chrome", current: 5, total: 7 }, "processing");
    const running = rows.findIndex((r) => r.state === "running");
    expect(running).toBe(4);
    expect(rows.slice(0, 4).every((r) => r.state === "completed")).toBe(true);
    expect(rows.slice(5).every((r) => r.state === "pending")).toBe(true);
  });

  it("shows the unknown step's own name rather than a label it is not", () => {
    const rows = stepStates({ step: "Polishing the chrome", current: 5, total: 5 }, "processing");
    expect(rows[4].label).toBe("Polishing the chrome");
  });

  it("recognises the edit job's per-fix steps", () => {
    const rows = stepStates({ step: "Applying fix 1/2", current: 1, total: 2 }, "processing");
    expect(rows[0].label).toBe("Tahrir qo'llanmoqda");
    expect(rows[0].state).toBe("running");
  });
});

describe("terminal states", () => {
  it("marks every row completed when the job completed", () => {
    const rows = stepStates({ step: "Rendering presentation", current: 7, total: 7 }, "completed");
    expect(rows.every((r) => r.state === "completed")).toBe(true);
  });

  it("marks the active row failed and leaves later rows pending", () => {
    const rows = stepStates({ step: "Choosing design direction", current: 4, total: 7 }, "failed");
    expect(rows[3].state).toBe("failed");
    expect(rows.slice(4).every((r) => r.state === "pending")).toBe(true);
  });

  it("shows nothing as started while the job is only queued", () => {
    const rows = stepStates({}, "queued");
    expect(rows.every((r) => r.state === "pending")).toBe(true);
  });

  it("treats a cancelled job like a failed one rather than a running one", () => {
    const rows = stepStates({ step: "Resolving images", current: 6, total: 7 }, "cancelled");
    expect(rows[5].state).toBe("failed");
  });
});

describe("out-of-range progress cannot break the render", () => {
  it("clamps a current past the end", () => {
    const rows = stepStates({ current: 99, total: 7 }, "processing");
    expect(rows.filter((r) => r.state === "running")).toHaveLength(1);
    expect(rows[6].state).toBe("running");
  });

  it("clamps a zero or negative current", () => {
    const rows = stepStates({ current: 0, total: 7 }, "processing");
    expect(rows[0].state).toBe("running");
  });
});
