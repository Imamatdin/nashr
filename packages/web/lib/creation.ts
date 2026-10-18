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
import type {
  InterviewQuestionView,
  InterviewView,
  PricingEntryView,
} from "@/lib/api";
import type { Locale } from "@/lib/locale";

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

const CREATION_COPY = {
  en: {
    skip: "Skip",
    minutes: "minutes",
    recommended: "recommended",
    customHint: "or write your own answer below",
    standard: "default",
    domains: {
      medical: "medicine",
      economics: "economics",
      legal: "law",
      engineering: "engineering",
      environmental: "environment",
      education: "education",
      agriculture: "agriculture",
      computer_science: "computer science",
      social_sciences: "social sciences",
      general: "general",
    },
    notReadyLead:
      "Sources are read during the first generation, so there are no questions yet. Nashr will make these decisions now.",
    notReadyLines: [
      "Audience: undergraduate students.",
      "Length: based on the amount of evidence in the sources.",
      "Headings: written as conclusions, with concise speaker notes.",
      "Design: a palette and mood selected for the topic.",
      "The next generation can ask questions derived from these sources.",
    ],
    domain: "Subject area",
    estimate: "Estimated length",
    slides: "slides",
    statsFound: (count: number) =>
      `${count} numerical facts found. They will receive dedicated slides.`,
    noStats:
      "No numerical facts found. The presentation will focus on textual evidence.",
    peopleFound: (count: number) =>
      `${count} people are mentioned and will be identified by name.`,
    remaining:
      "Audience, style, and interaction choices will follow the sources.",
    summaryLead: "If you skip the questions, Nashr will use these decisions.",
    labels: {
      topic: "Topic",
      language: "Language",
      package: "Package",
      slides: "Slides",
      formats: "Formats",
      images: "AI images",
      edits: "Edits",
      sources: "Sources",
      price: "Price",
      remaining: "Balance after charge",
    },
    byPackage: "depends on package",
    noImages: "none — typographic design",
    upTo: (count: number) => `up to ${count}`,
    none: "none",
    freeEdits: (count: number) => `${count} included edits`,
    sourceCount: (count: number) => String(count),
    charge:
      "Credit is charged now and refunded automatically if generation fails.",
    blocks: {
      topic: "Write the topic first.",
      uploading: "Sources are still uploading. Wait a moment.",
      failed: "No source was registered. Use Try again on the failed file.",
      missing:
        "Attach at least one source. Nashr only uses evidence from files you provide.",
    },
  },
  ru: {
    skip: "Пропустить",
    minutes: "минут",
    recommended: "рекомендуется",
    customHint: "или напишите свой ответ ниже",
    standard: "по умолчанию",
    domains: {
      medical: "медицина",
      economics: "экономика",
      legal: "право",
      engineering: "инженерия",
      environmental: "экология",
      education: "образование",
      agriculture: "сельское хозяйство",
      computer_science: "информатика",
      social_sciences: "общественные науки",
      general: "общая тема",
    },
    notReadyLead:
      "Источники читаются во время первой генерации, поэтому вопросов пока нет. Nashr примет эти решения сейчас.",
    notReadyLines: [
      "Аудитория: студенты бакалавриата.",
      "Длина: по объёму доказательств в источниках.",
      "Заголовки: в форме выводов, с краткими заметками докладчика.",
      "Дизайн: палитра и настроение под тему.",
      "При следующей генерации можно будет задать вопросы по этим источникам.",
    ],
    domain: "Направление",
    estimate: "Примерный объём",
    slides: "слайдов",
    statsFound: (count: number) =>
      `Найдено числовых фактов: ${count}. Для них будут отдельные слайды.`,
    noStats:
      "Числовых фактов не найдено. Акцент будет на текстовых доказательствах.",
    peopleFound: (count: number) =>
      `Упомянуто людей: ${count}. Они будут названы по имени.`,
    remaining:
      "Аудитория, стиль и интерактивность будут выбраны по источникам.",
    summaryLead: "Если пропустить вопросы, Nashr использует эти решения.",
    labels: {
      topic: "Тема",
      language: "Язык",
      package: "Пакет",
      slides: "Слайды",
      formats: "Форматы",
      images: "ИИ-изображения",
      edits: "Правки",
      sources: "Источники",
      price: "Цена",
      remaining: "Останется на балансе",
    },
    byPackage: "по пакету",
    noImages: "нет — типографический дизайн",
    upTo: (count: number) => `до ${count}`,
    none: "нет",
    freeEdits: (count: number) => `${count} правок включено`,
    sourceCount: (count: number) => String(count),
    charge:
      "Средства списываются сейчас и автоматически возвращаются, если генерация не завершится.",
    blocks: {
      topic: "Сначала укажите тему.",
      uploading: "Источники ещё загружаются. Подождите немного.",
      failed:
        "Ни один источник не зарегистрирован. Нажмите «Повторить» у файла с ошибкой.",
      missing:
        "Прикрепите хотя бы один источник. Nashr использует только доказательства из ваших файлов.",
    },
  },
  uz: {
    skip: "O‘tkazib yuborish",
    minutes: "daqiqa",
    recommended: "tavsiya etilgan",
    customHint: "quyidagi maydonga yozsangiz ham bo‘ladi",
    standard: "standart",
    domains: {
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
    },
    notReadyLead:
      "Manbalar birinchi generatsiya davomida o‘qiladi, shuning uchun hozir savol yo‘q — biz o‘zimiz qaror qilamiz.",
    notReadyLines: [
      "Auditoriya: bakalavr talabasi.",
      "Uzunlik: manbalardagi dalillar soniga qarab tanlanadi.",
      "Sarlavhalar: xulosa shaklida; ma’ruzachi izohlari qisqa tezislar bilan.",
      "Dizayn: mavzuga mos palitra va kayfiyat avtomatik tanlanadi.",
      "Keyingi generatsiyada shu manbalardan kelib chiqqan savollar beriladi.",
    ],
    domain: "Mavzu yo‘nalishi",
    estimate: "Taxminiy hajm",
    slides: "ta slayd",
    statsFound: (count: number) =>
      `Manbalarda ${count} ta raqamli dalil topildi — ular alohida slaydlarga chiqariladi.`,
    noStats:
      "Manbalarda raqamli dalil topilmadi — urg‘u matnli dalillarga beriladi.",
    peopleFound: (count: number) =>
      `${count} ta shaxs eslatilgan — ular nomma-nom keltiriladi.`,
    remaining:
      "Qolgan tanlovlar (auditoriya, uslub, interaktivlik) manbalarga qarab qo‘yiladi.",
    summaryLead: "Savollarga javob bermasangiz, quyidagicha qaror qilamiz.",
    labels: {
      topic: "Mavzu",
      language: "Til",
      package: "Paket",
      slides: "Slaydlar",
      formats: "Formatlar",
      images: "AI rasm",
      edits: "Tahrirlar",
      sources: "Manbalar",
      price: "Narx",
      remaining: "Keyin qoladi",
    },
    byPackage: "paket bo‘yicha",
    noImages: "yo‘q — tipografik dizayn",
    upTo: (count: number) => `${count} tagacha`,
    none: "yo‘q",
    freeEdits: (count: number) => `${count} ta bepul tuzatish`,
    sourceCount: (count: number) => `${count} ta`,
    charge:
      "Kredit hozir yechiladi; generatsiya muvaffaqiyatsiz tugasa, avtomatik qaytariladi.",
    blocks: {
      topic: "Avval mavzuni yozing.",
      uploading: "Manbalar hali yuklanmoqda — bir lahza kuting.",
      failed:
        "Hech bir manba ro‘yxatdan o‘tmadi — qatorlardagi «qayta urinish» tugmasini bosing.",
      missing:
        "Kamida bitta manba biriktiring — Nashr faqat siz bergan fayllardagi dalillarga tayanadi.",
    },
  },
  kaa: {
    skip: "Ótkerip jiberiw",
    minutes: "minut",
    recommended: "usınıs etilgen",
    customHint: "tómendegi maydanǵa jazsańız da boladı",
    standard: "standart",
    domains: {
      medical: "medicina",
      economics: "ekonomika",
      legal: "huqıq",
      engineering: "injenerlik",
      environmental: "ekologiya",
      education: "bilimlendiriw",
      agriculture: "awıl xojalıǵı",
      computer_science: "kompyuter ilimleri",
      social_sciences: "jámiyetlik ilimler",
      general: "ulıwma",
    },
    notReadyLead:
      "Derekler birinshi generaciya dawamında oqıladı, sonlıqtan házir soraw joq — biz ózimiz sheshim qabıl etemiz.",
    notReadyLines: [
      "Auditoriya: bakalavr studenti.",
      "Uzınlıǵı: dereklerdegi dáliller sanına qarap tańlanadı.",
      "Baslıqlar: juwmaq túrinde; dokladshı izoxları qısqa tezisler menen.",
      "Dizayn: temaǵa say palitra hám keypiyat avtomat túrde tańlanadı.",
      "Keyingi generaciyada usı dereklerden kelip shıqqan sorawlar beriledi.",
    ],
    domain: "Tema baǵdarı",
    estimate: "Shama kólem",
    slides: "slayd",
    statsFound: (count: number) =>
      `Dereklerde ${count} sanlı dálil tabıldı — olar ayrıqsha slaydlarǵa shıǵarıladı.`,
    noStats:
      "Dereklerde sanlı dálil tabılmadı — itibar tekstli dálillerge beriledi.",
    peopleFound: (count: number) =>
      `${count} adam eslatılǵan — olar atı menen keltiriledi.`,
    remaining:
      "Qalǵan tańlawlar (auditoriya, uslıp, interaktivlik) dereklerge qarap qoyıladı.",
    summaryLead: "Sorawlarǵa juwap bermeseńiz, tómendegishe sheshim qabıl etemiz.",
    labels: {
      topic: "Tema",
      language: "Til",
      package: "Paket",
      slides: "Slaydlar",
      formats: "Formatlar",
      images: "AI súwret",
      edits: "Redaktorlawlar",
      sources: "Derekler",
      price: "Baha",
      remaining: "Keyin qaladı",
    },
    byPackage: "paket boyınsha",
    noImages: "joq — tipografikalıq dizayn",
    upTo: (count: number) => `${count} ǵa shekem`,
    none: "joq",
    freeEdits: (count: number) => `${count} bepul dúzetiw`,
    sourceCount: (count: number) => String(count),
    charge:
      "Kredit házir alınadı; generaciya sátsiz tamamlansa, avtomat túrde qaytarıladı.",
    blocks: {
      topic: "Aldın temanı jazıń.",
      uploading: "Derekler ele júklenbekte — bir dem kútiń.",
      failed:
        "Hesh bir derek dizimnen ótpedi — qatarlardaǵı «qayta urınıw» túymesin basıń.",
      missing:
        "Keminde bir derek biriktiriń — Nashr tek siz bergen fayllardaǵı dálillerge súyenedi.",
    },
  },
} as const;

/** Discrete stops for the duration slider, clamped into the question's range. */
function sliderStops(question: InterviewQuestionView): number[] {
  const min = question.min_value ?? 5;
  const max = question.max_value ?? 45;
  const stops = [10, 15, 20, 30, 45].filter(
    (value) => value >= min && value <= max,
  );
  return stops.length > 0 ? stops : [min, max];
}

function kindOf(questionType: string): QuestionKind {
  if (questionType === "multi_select") return "multi";
  if (questionType === "slider") return "slider";
  if (questionType === "single_select") return "single";
  return "text";
}

function prepareOne(
  question: InterviewQuestionView,
  locale: Locale,
): PreparedQuestion {
  const copy = CREATION_COPY[locale];
  const kind = kindOf(question.question_type);
  const valueByLabel: Record<string, string> = {};

  if (kind === "slider") {
    const defaultValue = Number(question.default_value ?? 15);
    const options = sliderStops(question).map((minutes) => {
      const label = `${minutes} ${copy.minutes}`;
      valueByLabel[label] = String(minutes);
      return minutes === defaultValue
        ? { label, hint: copy.recommended }
        : { label };
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
    valueByLabel[copy.skip] = SKIP_ANSWER;
    return {
      questionId: question.question_id,
      kind,
      card: {
        q: question.help_text
          ? `${question.question_text} — ${question.help_text}`
          : question.question_text,
        type: "radio",
        options: [{ label: copy.skip, hint: copy.customHint }],
      },
      valueByLabel,
    };
  }

  const options = (question.options ?? []).map((option) => {
    valueByLabel[option.label] = option.value;
    return option.is_default
      ? { label: option.label, hint: copy.standard }
      : { label: option.label };
  });
  return {
    questionId: question.question_id,
    kind,
    card: {
      q: question.question_text,
      type: kind === "multi" ? "check" : "radio",
      options,
    },
    valueByLabel,
  };
}

export function prepareQuestions(
  view: InterviewView,
  locale: Locale = "uz",
): PreparedQuestion[] {
  return view.questions.map((question) => prepareOne(question, locale));
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
      .filter(
        (value): value is string => Boolean(value) && value !== SKIP_ANSWER,
      );

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

export function domainName(domain: string, locale: Locale = "uz"): string {
  const names = CREATION_COPY[locale].domains as Record<string, string>;
  return names[domain] ?? domain;
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
export function decisionSummary(
  view: InterviewView | null,
  locale: Locale = "uz",
): DecisionSummary {
  const copy = CREATION_COPY[locale];
  if (!view) {
    return {
      kind: "sources_not_ready",
      lead: copy.notReadyLead,
      lines: [...copy.notReadyLines],
    };
  }

  const lines = [
    `${copy.domain}: ${domainName(view.detected_domain, locale)}.`,
    `${copy.estimate}: ${view.estimated_slide_count} ${copy.slides}.`,
  ];
  lines.push(
    view.available_stats_count > 0
      ? copy.statsFound(view.available_stats_count)
      : copy.noStats,
  );
  if (view.available_people_count > 0) {
    lines.push(copy.peopleFound(view.available_people_count));
  }
  lines.push(copy.remaining);

  return {
    kind: "from_sources",
    lead: copy.summaryLead,
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
export function planRows(input: PlanInput, locale: Locale = "uz"): PlanRow[] {
  const copy = CREATION_COPY[locale];
  const labels = copy.labels;
  const price = input.pricing?.price ?? input.fallbackPrice;
  const rows: PlanRow[] = [
    { label: labels.topic, value: input.topic },
    { label: labels.language, value: input.languageLabel },
    { label: labels.package, value: input.packageLabel },
  ];

  if (input.estimatedSlides !== null) {
    rows.push({
      label: labels.slides,
      value: `~${input.estimatedSlides}`,
      mono: true,
    });
  }
  rows.push({ label: labels.formats, value: FORCED_FORMATS });
  rows.push({
    label: labels.images,
    value:
      input.pricing === null
        ? copy.byPackage
        : input.pricing.ai_images === 0
          ? copy.noImages
          : copy.upTo(input.pricing.ai_images),
    mono: input.pricing !== null && input.pricing.ai_images > 0,
  });
  if (input.pricing !== null) {
    rows.push({
      label: labels.edits,
      value:
        input.pricing.fix_allowance === 0
          ? copy.none
          : copy.freeEdits(input.pricing.fix_allowance),
      mono: input.pricing.fix_allowance > 0,
    });
  }
  rows.push({
    label: labels.sources,
    value: copy.sourceCount(input.sourceCount),
    mono: true,
  });
  rows.push({ label: labels.price, value: input.soum(price), mono: true });
  if (input.balance !== null) {
    rows.push({
      label: labels.remaining,
      value: input.soum(Math.max(0, input.balance - price)),
      mono: true,
    });
  }
  return rows;
}

/** The money sentence the card must carry — a promise, not a footnote. */
export const CHARGE_NOTE =
  "Kredit hozir yechiladi; generatsiya muvaffaqiyatsiz tugasa, avtomatik qaytariladi.";

export function chargeNote(locale: Locale = "uz"): string {
  return CREATION_COPY[locale].charge;
}

/**
 * Why the submit is blocked, or null when it is not.
 *
 * The API requires at least one source (`sources: min_length=1`). The composer
 * used to invite a sourceless run, get a pydantic array back, and offer a
 * retry that re-sent the identical doomed request (G9). The rule lives here so
 * the hint copy, the disabled state and the guard cannot drift apart.
 */
export function submitBlock(
  state: {
    hasTopic: boolean;
    uploading: boolean;
    readyCount: number;
    failedCount: number;
  },
  locale: Locale = "uz",
): string | null {
  const copy = CREATION_COPY[locale].blocks;
  if (!state.hasTopic) return copy.topic;
  if (state.uploading) return copy.uploading;
  if (state.readyCount === 0) {
    return state.failedCount > 0 ? copy.failed : copy.missing;
  }
  return null;
}
