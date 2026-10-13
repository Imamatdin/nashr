import { describe, expect, it } from "vitest";
import type { JobView } from "./api";
import {
  POLL_FIRST_MS,
  POLL_MAX_MS,
  deliveryFingerprint,
  isInFlight,
  nextPollDelay,
  settledDeliveries,
} from "./delivery";

function job(over: Partial<JobView> = {}): JobView {
  return {
    id: "j1",
    project_id: "p1",
    job_type: "presentation_generation",
    status: "committed",
    progress: {},
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
    render_status: "queued",
    render_progress: {},
    ...over,
  };
}

describe("nextPollDelay", () => {
  it("starts at 3 s and backs off to a 30 s ceiling, never stopping", () => {
    const delays: number[] = [];
    let delay: number | null = null;
    for (let i = 0; i < 12; i += 1) {
      delay = nextPollDelay(delay);
      delays.push(delay);
    }
    expect(delays[0]).toBe(POLL_FIRST_MS);
    expect(delays[1]).toBe(4_500);
    expect(Math.max(...delays)).toBe(POLL_MAX_MS);
    expect(delays.at(-1)).toBe(POLL_MAX_MS);
    for (let i = 1; i < delays.length; i += 1) expect(delays[i]).toBeGreaterThanOrEqual(delays[i - 1]);
  });
});

describe("isInFlight", () => {
  it("is true while the parent runs or is committed and delivering", () => {
    expect(isInFlight(job({ status: "queued", render_status: null }))).toBe(true);
    expect(isInFlight(job({ status: "processing", render_status: null }))).toBe(true);
    expect(isInFlight(job({ status: "committed" }))).toBe(true);
  });
  it("is false once the delivery settled either way", () => {
    expect(isInFlight(job({ status: "completed", render_status: "completed" }))).toBe(false);
    expect(isInFlight(job({ status: "delivery_failed", render_status: "failed" }))).toBe(false);
    expect(isInFlight(null)).toBe(false);
  });
});

describe("deliveryFingerprint", () => {
  it("changes on every render transition the downloads depend on", () => {
    const prints = [
      job({ status: "processing", render_job_id: null, render_status: null }),
      job({ status: "committed", render_status: "queued" }),
      job({ status: "committed", render_status: "processing", render_progress: { step: "html" } }),
      job({ status: "committed", render_status: "processing", render_progress: { step: "pdf" } }),
      job({ status: "completed", render_status: "completed" }),
    ].map(deliveryFingerprint);
    expect(new Set(prints).size).toBe(prints.length);
  });
  it("is stable while nothing changed", () => {
    expect(deliveryFingerprint(job())).toBe(deliveryFingerprint(job()));
  });
});

describe("settledDeliveries", () => {
  it("names the edits that left the delivering set", () => {
    expect(settledDeliveries(["a", "b"], ["b"])).toEqual(["a"]);
    expect(settledDeliveries(["a"], ["a", "c"])).toEqual([]);
  });
});
