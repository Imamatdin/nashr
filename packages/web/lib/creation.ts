// The decision logic behind the creation flow's clarification turn (G2) and
// its approval card (G31), kept DOM-free so it can be tested directly.
//
// Two facts shape everything here:
//
//   * The interview questions are derived from PROCESSED sources, and nothing
//     processes sources before enqueue. A first run therefore always answers
//     409 `sources_not_ready`. That is a designed state: the flow states what
//     it will decide on the user's behalf and says questions arrive next time.
//   * The engine keys answers by `question_id` and matches OPTION VALUES
//     against its enums. The approval card speaks in labels, so the mapping
//     back to values lives here — a label sent as a value silently falls
//     through to the server default, which is exactly the silent-defaults
//     complaint the interview exists to fix.

import type { ApprovalAnswer, ApprovalQuestion } from "@/components/bui";
import type { InterviewQuestionView, InterviewView, PricingEntryView } from "@/lib/api";

/** The sentinel the interview engine already understands for "you choose". */
export const DECIDE_FOR_ME = "decide_for_me";

/** Our own sentinel for a free-text question the user declined to answer. */
export const SKIP_ANSWER = "__skip__";

export type QuestionKind = "single" | "multi" | "slider" | "text";

export interface PreparedQuestion {
  questionId: string;
  kind: QuestionKind;
  card: ApprovalQuestion;
  /** Option label → the value the engine matches on. */
  valueByLabel: Record<string, string>;
}

const SKIP_LABEL = "O‘tkazib yuborish";

/** Discrete stops for the duration slider, clamped into the question's range. */
function sliderStops(question: InterviewQuestionView): number[] {
  const min = question.min_value ?? 5;
  const max = question.max_value ?? 45;
  const stops = [10, 15, 20, 30, 45].filter((value) => value >= min && value <= max);
  return stops.length > 0 ? stops : [min, max];
}

function kindOf(questionType: string): QuestionKind {
  if (questionType === "multi_select") return "multi";
  if (questionType === "slider") return "slider";
  if (questionType === "single_select") return "single";
  return "text";
}

function prepareOne(question: InterviewQuestionView): PreparedQuestion {
  const kind = kindOf(question.question_type);
  const valueByLabel: Record<string, string> = {};

  if (kind === "slider") {
    const defaultValue = Number(question.default_value ?? 15);
    const options = sliderStops(question).map((minutes) => {
      const label = `${minutes} daqiqa`;
      valueByLabel[label] = String(minutes);
      return minutes === defaultValue ? { label, hint: "tavsiya etilgan" } : { label };
    });
    return {
      questionId: question.question_id,
      kind,
      card: { q: question.question_text, type: "radio", options },
      valueByLabel,
    };
  }

  if (kind === "text") {
    // A question with no options cannot be advanced past in the card — the
    // send arrow is gated on an answer — so declining has to be an option.
    valueByLabel[SKIP_LABEL] = SKIP_ANSWER;
    return {
      questionId: question.question_id,
      kind,
      card: {
        q: question.help_text
          ? `${question.question_text} — ${question.help_text}`
          : question.question_text,
        type: "radio",
        options: [{ label: SKIP_LABEL, hint: "quyidagi maydonga yozsangiz ham bo‘ladi" }],
      },
      valueByLabel,
    };
  }

  const options = (question.options ?? []).map((option) => {
    valueByLabel[option.label] = option.value;
    return option.is_default ? { label: option.label, hint: "standart" } : { label: option.label };
  });
  return {
    questionId: question.question_id,
    kind,
    card: { q: question.question_text, type: kind === "multi" ? "check" : "radio", options },
    valueByLabel,
  };
}

export function prepareQuestions(view: InterviewView): PreparedQuestion[] {
  return view.questions.map(prepareOne);
}

export type AnswerValue = string | number | string[];

/**
 * Fold the card's label-shaped answers into the engine's value-shaped payload.
 *
 * Anything we cannot map to a value the engine knows is DROPPED rather than
 * sent: the card's free-text field is card-wide, so a typed sentence against a
 * select question would be an enum miss server-side. Omitting the key lets the
 * engine apply its own default, which is the same outcome without the lie.
 */
export function buildAnswers(
  prepared: PreparedQuestion[],
  answers: ApprovalAnswer[],
): Record<string, AnswerValue> {
  const payload: Record<string, AnswerValue> = {};
  prepared.forEach((question, index) => {
    const answer = answers[index];
    if (!answer) return;
    const values = answer.selected
      .map((label) => question.valueByLabel[label])
      .filter((value): value is string => Boolean(value) && value !== SKIP_ANSWER);

    if (question.kind === "text") {
      const typed = answer.custom?.trim();
      if (typed) payload[question.questionId] = typed;
      return;
    }
    if (question.kind === "multi") {
      if (values.length > 0) payload[question.questionId] = values;
      return;
    }
    if (question.kind === "slider") {
      const minutes = Number(values[0]);
      if (Number.isFinite(minutes)) payload[question.questionId] = minutes;
      return;
    }
    if (values.length > 0) payload[question.questionId] = values[0];
  });
  return payload;
}

const DOMAIN_NAMES: Record<string, string> = {
  medical: "tibbiyot",
  economics: "iqtisodiyot",
  legal: "huquq",
  engineering: "muhandislik",
  environmental: "ekologiya",
  education: "ta’lim",
  agriculture: "qishloq xo‘jaligi",
  computer_science: "kompyuter fanlari",
  social_sciences: "ijtimoiy fanlar",
  general: "umumiy",
};

export function domainName(domain: string): string {
  return DOMAIN_NAMES[domain] ?? domain;
}

export interface DecisionSummary {
  /** Whether the interview answered, or told us the sources are not read yet. */
  kind: "from_sources" | "sources_not_ready";
  /** One honest sentence about why we are deciding instead of asking. */
  lead: string;
  /** The concrete decisions, each a full sentence. */
  lines: string[];
}

/**
 * What "O‘zingiz tanlang" actually decides, said out loud.
 *
 * The audit's complaint about G2 is not that defaults exist — it is that they
 * were applied in silence. Passing null (the 409 path) still produces copy;
 * it just cannot name a domain or a slide count yet.
 */
export function decisionSummary(view: InterviewView | null): DecisionSummary {
  if (!view) {
    return {
      kind: "sources_not_ready",
      lead: "Manbalar birinchi generatsiya davomida o‘qiladi, shuning uchun hozir savol yo‘q — biz o‘zimiz qaror qilamiz.",
      lines: [
        "Auditoriya: bakalavr talabasi.",
        "Uzunlik: manbalardagi dalillar soniga qarab tanlanadi.",
        "Sarlavhalar: xulosa shaklida; ma’ruzachi izohlari qisqa tezislar bilan.",
        "Dizayn: mavzuga mos palitra va kayfiyat avtomatik tanlanadi.",
        "Keyingi generatsiyada shu manbalardan kelib chiqqan savollar beriladi.",
      ],
    };
  }

  const lines = [
    `Mavzu yo‘nalishi: ${domainName(view.detected_domain)}.`,
    `Taxminiy hajm: ${view.estimated_slide_count} ta slayd.`,
  ];
  lines.push(
    view.available_stats_count > 0
      ? `Manbalarda ${view.available_stats_count} ta raqamli dalil topildi — ular alohida slaydlarga chiqariladi.`
      : "Manbalarda raqamli dalil topilmadi — urg‘u matnli dalillarga beriladi.",
  );
  if (view.available_people_count > 0) {
    lines.push(`${view.available_people_count} ta shaxs eslatilgan — ular nomma-nom keltiriladi.`);
  }
  lines.push("Qolgan tanlovlar (auditoriya, uslub, interaktivlik) manbalarga qarab qo‘yiladi.");

  return {
    kind: "from_sources",
    lead: "Savollarga javob bermasangiz, quyidagicha qaror qilamiz.",
    lines,
  };
}

export interface PlanRow {
  label: string;
  value: string;
  /** Machine facts (prices, counts) render in the mono face. */
  mono?: boolean;
}

export interface PlanInput {
  topic: string;
  languageLabel: string;
  packageLabel: string;
  sourceCount: number;
  /** Server truth from GET /pricing; null until it loads (or if it fails). */
  pricing: PricingEntryView | null;
  /** lib/packages.ts list price — a FALLBACK only. */
  fallbackPrice: number;
  /** Server truth from GET /credits; null until it loads. */
  balance: number | null;
  /** From the interview, when it gave one. */
  estimatedSlides: number | null;
  soum: (amount: number) => string;
}

/** Every output format is forced server-side, so the card can state all three. */
export const FORCED_FORMATS = "HTML (interaktiv) · PDF · PPTX";

/**
 * The approval card's rows. The audit's G31 finding is that the card priced
 * the run without ever saying what the run DOES; every row past "Narx" exists
 * to answer that, and the money rows come from the server, not from the
 * client's price table.
 */
export function planRows(input: PlanInput): PlanRow[] {
  const price = input.pricing?.price ?? input.fallbackPrice;
  const rows: PlanRow[] = [
    { label: "Mavzu", value: input.topic },
    { label: "Til", value: input.languageLabel },
    { label: "Paket", value: input.packageLabel },
  ];

  if (input.estimatedSlides !== null) {
    rows.push({ label: "Slaydlar", value: `~${input.estimatedSlides} ta`, mono: true });
  }
  rows.push({ label: "Formatlar", value: FORCED_FORMATS });
  rows.push({
    label: "AI rasm",
    value:
      input.pricing === null
        ? "paket bo‘yicha"
        : input.pricing.ai_images === 0
          ? "yo‘q — tipografik dizayn"
          : `${input.pricing.ai_images} tagacha`,
    mono: input.pricing !== null && input.pricing.ai_images > 0,
  });
  if (input.pricing !== null) {
    rows.push({
      label: "Tahrirlar",
      value:
        input.pricing.fix_allowance === 0
          ? "yo‘q"
          : `${input.pricing.fix_allowance} ta bepul tuzatish`,
      mono: input.pricing.fix_allowance > 0,
    });
  }
  rows.push({ label: "Manbalar", value: `${input.sourceCount} ta`, mono: true });
  rows.push({ label: "Narx", value: input.soum(price), mono: true });
  if (input.balance !== null) {
    rows.push({
      label: "Keyin qoladi",
      value: input.soum(Math.max(0, input.balance - price)),
      mono: true,
    });
  }
  return rows;
}

/** The money sentence the card must carry — a promise, not a footnote. */
export const CHARGE_NOTE =
  "Kredit hozir yechiladi; generatsiya muvaffaqiyatsiz tugasa, avtomatik qaytariladi.";

/**
 * Why the submit is blocked, or null when it is not.
 *
 * The API requires at least one source (`sources: min_length=1`). The composer
 * used to invite a sourceless run, get a pydantic array back, and offer a
 * retry that re-sent the identical doomed request (G9). The rule lives here so
 * the hint copy, the disabled state and the guard cannot drift apart.
 */
export function submitBlock(state: {
  hasTopic: boolean;
  uploading: boolean;
  readyCount: number;
  failedCount: number;
}): string | null {
  if (!state.hasTopic) return "Avval mavzuni yozing.";
  if (state.uploading) return "Manbalar hali yuklanmoqda — bir lahza kuting.";
  if (state.readyCount === 0) {
    return state.failedCount > 0
      ? "Hech bir manba ro‘yxatdan o‘tmadi — qatorlardagi «qayta urinish» tugmasini bosing."
      : "Kamida bitta manba biriktiring — Nashr faqat siz bergan fayllardagi dalillarga tayanadi.";
  }
  return null;
}
