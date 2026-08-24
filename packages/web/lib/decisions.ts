// Turning the pipeline's persisted decisions into things a person can read.
//
// G14 is rated S1 and is the last of the audit's S1 rows: "the system never
// shows what it decided". The deck has always carried its own design direction,
// its binding plan and its resolved preferences; the workspace could only ever
// repeat the seven step labels back. These helpers are the vocabulary layer —
// the enum values the backend stores are machine words, and a teacher should
// not be shown `warm_historical` or `results_numbers`.
//
// An unmapped value falls back to the raw token rather than to a wrong guess:
// a new mood added backend-side should read oddly, not incorrectly.

import type { DecisionsView } from "./api";

const MOOD: Record<string, string> = {
  warm_historical: "Iliq, tarixiy",
  clean_modern: "Toza, zamonaviy",
  bold_editorial: "Qat’iy, jurnal uslubi",
  quiet_academic: "Vazmin, akademik",
  vivid_scientific: "Yorqin, ilmiy",
};

const BACKGROUND: Record<string, string> = {
  dark: "To‘q fon",
  light: "Yorug‘ fon",
  gradient: "Gradient",
  texture: "Tekstura",
  image: "Rasm",
};

const AUDIENCE: Record<string, string> = {
  school: "Maktab o‘quvchilari",
  undergraduate: "Bakalavr talabalari",
  graduate: "Magistratura talabalari",
  academic_conference: "Akademik konferentsiya",
  mixed_academic_industry: "Akademik va sanoat aralash",
  professional: "Mutaxassislar",
  general_public: "Keng jamoatchilik",
};

const EMPHASIS: Record<string, string> = {
  problem_framing: "Muammoni shakllantirish",
  technical_mechanism: "Texnik mexanizm",
  methodology: "Metodologiya",
  results_numbers: "Natijalar va raqamlar",
  roadmap_scalability: "Keyingi qadamlar",
  balanced: "Muvozanatli",
};

const PHASE: Record<string, string> = {
  hook: "Ochilish",
  context: "Kontekst",
  core: "Asosiy qism",
  evidence: "Dalillar",
  implications: "Oqibatlar",
  close: "Yakun",
};

function label(map: Record<string, string>, value: string): string {
  return map[value] ?? value;
}

export const moodLabel = (v: string) => label(MOOD, v);
export const backgroundLabel = (v: string) => label(BACKGROUND, v);
export const audienceLabel = (v: string) => label(AUDIENCE, v);
export const emphasisLabel = (v: string) => label(EMPHASIS, v);
export const phaseLabel = (v: string) => label(PHASE, v);

export interface DecidedFact {
  label: string;
  value: string;
}

/**
 * The choices the pipeline made ON THE USER'S BEHALF.
 *
 * The audit's complaint about `apply_defaults` is not that it decides — it is
 * that it decides SILENTLY. Naming them is the whole point, so this returns
 * them even when the user answered the interview themselves: "what is this
 * deck built to" is worth knowing either way.
 */
export function decidedFor(view: DecisionsView): DecidedFact[] {
  return [
    { label: "Auditoriya", value: audienceLabel(view.audience) },
    { label: "Davomiylik", value: `${view.talk_duration_minutes} daqiqa` },
    { label: "Urg‘u", value: emphasisLabel(view.narrative_emphasis) },
    {
      label: "Interaktiv",
      value: view.include_interactive ? "Bor" : "Yo‘q",
    },
    { label: "Slaydlar", value: `${view.slide_count} ta` },
  ];
}

/** The palette as swatches — a hex string is not a colour to a reader. */
export function swatches(view: DecisionsView): Array<{ name: string; hex: string }> {
  return [
    { name: "Fon", hex: view.palette.background },
    { name: "Yuza", hex: view.palette.surface },
    { name: "Matn", hex: view.palette.text },
    { name: "Urg‘u", hex: view.palette.accent },
  ];
}

/** True when the deck predates the binding planner and has no argument to show. */
export function hasArgument(view: DecisionsView): boolean {
  return view.thesis !== null && view.sections.length > 0;
}
