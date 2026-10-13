// Asynchronous delivery (B1-FIX2).
//
// A paid generation or a queued AI edit commits its revision and then waits for
// a separate render job to publish the files. The parent job reads 'committed'
// until that render settles it ('completed', or 'delivery_failed' and refunded).
// These helpers decide WHEN the workspace re-reads: polling never depends on
// Realtime or on a deck already existing, and it backs off from 3 s to 30 s.

import type { JobView } from "./api";

export const POLL_FIRST_MS = 3_000;
export const POLL_MAX_MS = 30_000;
const POLL_GROWTH = 1.5;

/** The next delay of a backing-off poll: 3 s, 4.5 s, … capped at 30 s. */
export function nextPollDelay(previous: number | null): number {
  if (previous === null) return POLL_FIRST_MS;
  return Math.min(POLL_MAX_MS, Math.round(previous * POLL_GROWTH));
}

/** True while the job still owes the project something: running or delivering. */
export function isInFlight(job: JobView | null): boolean {
  if (job === null) return false;
  if (job.status === "queued" || job.status === "processing" || job.status === "committed")
    return true;
  return job.render_status === "queued" || job.render_status === "processing";
}

/**
 * Everything about a job's delivery that should make the workspace re-read its
 * exports: the parent's status and the render's status and progress. When it
 * changes — the render started, published a format, finished or failed — the
 * download links are refreshed, with or without Realtime and with or without a
 * deck response yet.
 */
export function deliveryFingerprint(job: JobView | null): string {
  if (job === null) return "none";
  const progress = job.render_progress ?? {};
  return [
    job.id,
    job.status,
    job.render_job_id ?? "-",
    job.render_status ?? "-",
    typeof progress.step === "string" ? progress.step : "-",
    typeof progress.current === "number" ? String(progress.current) : "-",
  ].join("|");
}

/** Delivering edit jobs that settled between two chat reads. */
export function settledDeliveries(previous: readonly string[], next: readonly string[]): string[] {
  const still = new Set(next);
  return previous.filter((id) => !still.has(id));
}
