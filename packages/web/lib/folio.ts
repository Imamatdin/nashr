// Pure helpers behind the folio (/projects).
//
// Three audit gaps live here:
//
//   G12/G33 — the list read was a `.then` with no `.catch` and no timeout, and
//             supabase-js does NOT throw on a dead network: it resolves with
//             `{ data: null, error, status: 0 }`. So a catch alone fixes
//             nothing. `supabaseFailure` is the real repair — it turns the
//             PostgREST envelope into a value `describeError` already knows how
//             to speak about, so an unreachable backend reads as "Internet
//             uzildi" instead of five grey bars forever.
//   G25     — rows carried a status chip and nothing else. `liveStatusOf`,
//             `stepLabelOf` and `elapsedLabel` derive what a generating row is
//             actually doing from the newest generation_jobs row for it.
//
// `liveStatusOf` is the single source of truth for BOTH the badge and the
// filter chip: derived separately they drift, and a row can sit under
// "Qoralama" while its badge says "Yaratilmoqda".

import { ApiError } from "./api";
import { type Progress, stepStates } from "./steps";

export interface JobSnapshot {
  id: string;
  projectId: string;
  status: string;
  progress: Progress;
  createdAt: string | null;
  startedAt: string | null;
}

/** Statuses that mean "the worker still owes this project something". */
const ACTIVE = new Set(["queued", "processing"]);

export function isTerminalJob(status: string): boolean {
  return !ACTIVE.has(status);
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/**
 * Map one raw row — a PostgREST select or a Realtime `payload.new` record —
 * into the shape the list renders from. Anything that is not recognisably a
 * job row returns null rather than riding into the UI half-formed.
 */
export function jobSnapshot(raw: unknown): JobSnapshot | null {
  if (typeof raw !== "object" || raw === null) return null;
  const row = raw as Record<string, unknown>;
  const id = str(row.id);
  const projectId = str(row.project_id);
  const status = str(row.status);
  if (!id || !projectId || !status) return null;
  const progress =
    typeof row.progress === "object" && row.progress !== null
      ? (row.progress as Progress)
      : ({} as Progress);
  return {
    id,
    projectId,
    status,
    progress,
    createdAt: str(row.created_at),
    startedAt: str(row.started_at),
  };
}

/**
 * Realtime delivers events in arrival order, which is not creation order after
 * a reconnect replay. A later event about an OLDER job must not overwrite the
 * run the user is watching.
 */
export function isNewerJob(next: JobSnapshot, held: JobSnapshot): boolean {
  if (next.id === held.id) return true; // same run, later state
  return (next.createdAt ?? "") >= (held.createdAt ?? "");
}

/** Newest active job per project, from a flat query result. */
export function newestByProject(rows: readonly unknown[]): Record<string, JobSnapshot> {
  const map: Record<string, JobSnapshot> = {};
  for (const raw of rows) {
    const snapshot = jobSnapshot(raw);
    if (!snapshot || isTerminalJob(snapshot.status)) continue;
    const held = map[snapshot.projectId];
    if (!held || isNewerJob(snapshot, held)) map[snapshot.projectId] = snapshot;
  }
  return map;
}

/**
 * Fold one Realtime event into the live map. A terminal status drops the entry
 * — what the project becomes is then re-read from the database rather than
 * guessed at here.
 */
export function applyJob(
  current: Readonly<Record<string, JobSnapshot>>,
  next: JobSnapshot,
): Record<string, JobSnapshot> {
  const held = current[next.projectId];
  if (held && !isNewerJob(next, held)) return current;
  if (isTerminalJob(next.status)) {
    if (!held) return current;
    const pruned = { ...current };
    delete pruned[next.projectId];
    return pruned;
  }
  return { ...current, [next.projectId]: next };
}

// ------------------------------------------------------------------ status

const CHIP_STATUSES: Record<string, readonly string[]> = {
  draft: ["draft", "sourcing", "interview"],
  generating: ["generating", "queued", "processing"],
  ready: ["ready", "completed"],
  failed: ["failed", "cancelled"],
  archived: ["archived"],
};

/** Which lifecycle chip a status belongs under. */
export function chipOf(status: string): string {
  for (const [key, statuses] of Object.entries(CHIP_STATUSES)) {
    if (statuses.includes(status)) return key;
  }
  return "other";
}

/**
 * The status a row should show right now. A live job outranks the projects
 * row, which the worker only stamps at the end of a run: a project still
 * marked `draft` whose job is processing is generating, whatever the column says.
 */
export function liveStatusOf(projectStatus: string, job: JobSnapshot | null): string {
  if (!job || isTerminalJob(job.status)) return projectStatus;
  return job.status === "queued" ? "queued" : "generating";
}

/** "4/7 · Dizayn yo‘nalishi tanlanmoqda" — which step, not just "busy". */
export function stepLabelOf(job: JobSnapshot | null): string | null {
  if (!job || job.status !== "processing") return null;
  const running = stepStates(job.progress, job.status).find((row) => row.state === "running");
  if (!running) return null;
  return `${running.meta} · ${running.label}`;
}

/** How long this run has been going. Null once it is no longer running. */
export function elapsedLabel(job: JobSnapshot | null, now: number): string | null {
  if (!job || isTerminalJob(job.status)) return null;
  const start = job.startedAt ?? job.createdAt;
  if (!start) return null;
  const began = new Date(start).getTime();
  if (!Number.isFinite(began)) return null;
  const seconds = Math.floor((now - began) / 1000);
  if (seconds < 0) return null;
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} daq`;
  const hours = Math.floor(minutes / 60);
  return `${hours} soat ${minutes % 60} daq`;
}

// ----------------------------------------------------------------- failure

export interface PostgrestFailure {
  message: string;
  code?: string;
  details?: string;
  hint?: string;
}

/**
 * Turn a PostgREST envelope failure into something `describeError` can speak
 * about in Uzbek. The envelope's `status` is 0 for anything that never reached
 * the server, and an aborted request keeps its AbortError name in `message`.
 *
 * The reason string deliberately carries a space, so `reasonOf` declines to
 * treat it as a code and the copy falls through to the status catalog while
 * the machine text still survives into "Texnik tafsilot".
 */
export function supabaseFailure(
  error: PostgrestFailure | null | undefined,
  status: number,
): unknown {
  const message = error?.message ?? "unknown";
  const code = error?.code ?? "";
  if (message.startsWith("AbortError") || code === "ABORT_ERR") {
    return new DOMException(message, "AbortError");
  }
  if (status === 0) return new TypeError(message);
  const reason = code ? `${code}: ${message}` : message;
  return new ApiError(status >= 400 ? status : 500, reason);
}
