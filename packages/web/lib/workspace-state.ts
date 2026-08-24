// The workspace's state, derived from PROJECT + LATEST JOB.
//
// The audit's single worst defect (G3, and G5 as its twin) was that the
// workspace discovered a run only from the `?job=` URL param. Open a
// generating, failed or delivered project from the folio and you got the idle
// sales pitch — "Taqdimot yaratish · 10 000 so'm" — over a project that was
// mid-run, or already paid for, or already delivered. On a failed or ready
// project that click was a genuine second charge, and on a ready one it
// overwrote the only deck row.
//
// The fix is not a bug fix, it is a state model. `?job=` becomes a focus hint;
// the state comes from the project row and `GET /jobs?project_id=`. Every state
// below has exactly one designed screen, and the enqueue CTA is reachable from
// exactly one of them.

import type { JobView } from "./api";

export type WorkspaceStateKind =
  | "loading"
  | "article_project"
  | "archived"
  | "no_job"
  | "queued"
  | "processing"
  | "failed"
  | "completed_no_deck"
  | "ready";

export interface WorkspaceState {
  kind: WorkspaceStateKind;
  job: JobView | null;
  /**
   * The ONLY flag that may render a priced start button. Never true while a
   * job is running, and on ready/failed it means the separately-worded
   * regenerate — never the idle pitch.
   */
  canEnqueue: boolean;
  /** True where the CTA must say it is a NEW paid run, not a resume. */
  enqueueIsRepeat: boolean;
}

export interface ProjectShape {
  status: string;
  /** `projects.type` — presentation | article | … */
  project_type?: string | null;
}

/** Statuses the queue considers live. */
export function isRunning(job: JobView | null): boolean {
  return job !== null && (job.status === "queued" || job.status === "processing");
}

/**
 * Derive the workspace state.
 *
 * `job === null` means the discovery route answered 404 — "this project has
 * never been generated" — which is a state, not an error. `deckReady` is the
 * deck route's own answer, because a completed job whose files have not landed
 * yet is a WAIT (G7), not a delivery.
 */
export function deriveWorkspaceState(
  project: ProjectShape | null,
  job: JobView | null,
  deckReady: boolean,
  jobLoaded: boolean,
): WorkspaceState {
  if (project === null || !jobLoaded) {
    return { kind: "loading", job, canEnqueue: false, enqueueIsRepeat: false };
  }

  // An article project is not a presentation priced as one (G13). Checked
  // before anything else: none of the presentation states apply to it.
  const type = (project.project_type ?? "presentation").toLowerCase();
  if (type !== "presentation") {
    return { kind: "article_project", job, canEnqueue: false, enqueueIsRepeat: false };
  }

  // Archived is a state the UI could previously neither enter nor leave, while
  // still offering a purchasable run inside it (G37).
  if (project.status === "archived") {
    return { kind: "archived", job, canEnqueue: false, enqueueIsRepeat: false };
  }

  if (job === null) {
    return { kind: "no_job", job: null, canEnqueue: true, enqueueIsRepeat: false };
  }

  if (job.status === "queued") {
    return { kind: "queued", job, canEnqueue: false, enqueueIsRepeat: false };
  }
  if (job.status === "processing") {
    return { kind: "processing", job, canEnqueue: false, enqueueIsRepeat: false };
  }
  if (job.status === "failed" || job.status === "cancelled") {
    // Retry is a NEW paid job from step 1, not a resume of the four steps that
    // already succeeded. The copy has to say so (G11).
    return { kind: "failed", job, canEnqueue: true, enqueueIsRepeat: true };
  }

  if (!deckReady) {
    return { kind: "completed_no_deck", job, canEnqueue: false, enqueueIsRepeat: false };
  }
  return { kind: "ready", job, canEnqueue: true, enqueueIsRepeat: true };
}

/** Milliseconds the run has been alive, from the job's own timestamps. */
export function elapsedMs(job: JobView | null, now = Date.now()): number | null {
  if (!job) return null;
  const startedRaw = job.started_at ?? job.created_at;
  if (!startedRaw) return null;
  const started = new Date(startedRaw).getTime();
  if (!Number.isFinite(started)) return null;
  const ended = job.completed_at ? new Date(job.completed_at).getTime() : now;
  return Math.max(0, (Number.isFinite(ended) ? ended : now) - started);
}

/** A queued job has not started; its wait is measured from creation. */
export function startedAtMs(job: JobView | null): number | undefined {
  if (!job) return undefined;
  const raw = job.started_at ?? job.created_at;
  if (!raw) return undefined;
  const at = new Date(raw).getTime();
  return Number.isFinite(at) ? at : undefined;
}

/**
 * The worker heartbeats every 15 s (HEARTBEAT_INTERVAL_SECONDS). Three missed
 * beats is a stall worth telling the user about — the reaper will not touch the
 * row until 120 s, so without this the UI claims progress for two minutes after
 * the worker died (G17).
 */
export const STALL_AFTER_MS = 45_000;

export function isStalled(job: JobView | null, now = Date.now()): boolean {
  if (!job || job.status !== "processing" || !job.heartbeat_at) return false;
  const beat = new Date(job.heartbeat_at).getTime();
  if (!Number.isFinite(beat)) return false;
  return now - beat > STALL_AFTER_MS;
}

export function formatElapsed(ms: number): string {
  const total = Math.floor(ms / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  if (minutes === 0) return `${seconds}s`;
  return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
}

/**
 * The badge status, derived from the SAME state the body renders from.
 *
 * `projects.status` is a denormalised column that drifts: a project row can say
 * "ready" while its latest job says otherwise, or while it has no job at all.
 * Reading it directly put "Tayyor" above "order a presentation" — a header and
 * a body disagreeing on the same screen, which is the whole class of defect
 * this phase exists to remove.
 */
export function badgeStatusFor(kind: WorkspaceStateKind, projectStatus: string): string {
  switch (kind) {
    case "no_job":
      return "draft";
    case "queued":
      return "queued";
    case "processing":
      // Files are still being written; the run is not over.
      return "processing";
    case "completed_no_deck":
      return "processing";
    case "failed":
      return "failed";
    case "ready":
      return "completed";
    case "archived":
      return "archived";
    default:
      // article_project / loading: the project's own status is the only fact.
      return projectStatus;
  }
}
