// The worker's 7 pipeline steps (progress.step strings), humanized. Keys must
// match packages/bot/orchestrators/presentation_orchestrator.py verbatim.

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

export function stepStates(
  progress: { step?: string; current?: number },
  status: string,
): Array<{ key: string; label: string; state: StepState }> {
  const last = STEP_LABELS.length - 1;
  const queued = status === "queued";
  const done = status === "completed";
  const named = STEP_LABELS.findIndex((entry) => entry.key === progress.step);
  const active =
    named >= 0 ? named : Math.max(0, Math.min((progress.current ?? 1) - 1, last));

  return STEP_LABELS.map((entry, index) => {
    let state: StepState = "pending";
    if (done) {
      state = "completed";
    } else if (!queued) {
      if (index < active) state = "completed";
      else if (index === active) state = status === "failed" ? "failed" : "running";
    }
    return { key: entry.key, label: entry.label, state };
  });
}
