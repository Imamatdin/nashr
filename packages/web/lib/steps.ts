// The worker's pipeline steps, humanized.
//
// Keys match packages/bot/orchestrators/presentation_orchestrator.py. They used
// to be asserted as the whole truth (G39): the list was hardcoded to seven, the
// `n/7` meta was a literal, and a step name the client did not recognise
// silently highlighted the wrong row — the UI would confidently claim step 4
// while the worker was somewhere else entirely.
//
// Now the wire wins. `progress.total` sets the denominator when the job sends
// one, and an unknown step name is rendered honestly by its number instead of
// being mapped onto a label that happens to sit at that index.

export type StepState = "pending" | "running" | "completed" | "failed";

export const STEP_LABELS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "Processing sources", label: "Manbalar o'qilmoqda" },
  { key: "Building evidence matrix", label: "Dalillar jamlanmoqda" },
  { key: "Applying preferences", label: "Talablar hisobga olinmoqda" },
  { key: "Choosing design direction", label: "Dizayn yo'nalishi tanlanmoqda" },
  { key: "Creating slide sequence", label: "Slaydlar ketma-ketligi tuzilmoqda" },
  { key: "Resolving images", label: "Vizuallar tayyorlanmoqda" },
  { key: "Rendering presentation", label: "Taqdimot yig'ilmoqda" },
];

// An edit job re-runs a short chain of its own; its step names are per-fix and
// not in the list above, so they resolve through the unknown-step path.
const EDIT_STEP_LABEL = "Tahrir qo'llanmoqda";

export interface Progress {
  step?: string;
  current?: number;
  total?: number;
}

export interface StepRow {
  key: string;
  label: string;
  state: StepState;
  /** "3/7" — from the wire's own total, not a hardcoded one. */
  meta: string;
}

function labelFor(stepName: string | undefined, index: number): string {
  // No stepName means "this is not the active row": position is all we know,
  // and the positional label is the right guess.
  if (stepName === undefined) return STEP_LABELS[index]?.label ?? `Bosqich ${index + 1}`;

  const known = STEP_LABELS.find((entry) => entry.key === stepName);
  if (known) return known.label;
  if (stepName.startsWith("Applying fix")) return EDIT_STEP_LABEL;
  // The worker named a step we do not have copy for. Showing it verbatim is
  // ugly; showing the label that happens to sit at this index would be a lie
  // about what the pipeline is doing — which is the defect G39 describes.
  return stepName;
}

/**
 * Rows for the pipeline display.
 *
 * The active row is resolved by NAME when the wire sends one we know, and by
 * `current` otherwise — never by name-matched-to-index, which is what let an
 * unrecognised step mis-highlight. When the job reports a `total` that differs
 * from our label list, the list is truncated or extended to match it, so the
 * UI never claims seven steps for a run that has three.
 */
export function stepStates(progress: Progress, status: string): StepRow[] {
  const total = Math.max(1, progress.total ?? STEP_LABELS.length);
  const queued = status === "queued";
  const done = status === "completed";
  const failed = status === "failed" || status === "cancelled";

  const named = STEP_LABELS.findIndex((entry) => entry.key === progress.step);
  const fromCurrent = Math.min(Math.max((progress.current ?? 1) - 1, 0), total - 1);
  const active = named >= 0 ? named : fromCurrent;

  return Array.from({ length: total }, (_, index) => {
    let state: StepState = "pending";
    if (done) {
      state = "completed";
    } else if (!queued) {
      if (index < active) state = "completed";
      else if (index === active) state = failed ? "failed" : "running";
    }
    return {
      key: STEP_LABELS[index]?.key ?? `step-${index + 1}`,
      label: index === active ? labelFor(progress.step, index) : labelFor(undefined, index),
      state,
      meta: `${index + 1}/${total}`,
    };
  });
}
