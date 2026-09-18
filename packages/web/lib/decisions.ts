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
import type { Locale } from "./locale";

const VOCABULARY = {
  en: {
    mood: {
      warm_historical: "Warm and historical",
      clean_modern: "Clean and modern",
      bold_editorial: "Bold editorial",
      quiet_academic: "Quiet academic",
      vivid_scientific: "Vivid scientific",
    },
    background: {
      dark: "Dark background",
      light: "Light background",
      gradient: "Gradient",
      texture: "Texture",
      image: "Image",
    },
    audience: {
      school: "School students",
      undergraduate: "Undergraduates",
      graduate: "Graduate students",
      academic_conference: "Academic conference",
      mixed_academic_industry: "Academic and industry",
      professional: "Professionals",
      general_public: "General public",
    },
    emphasis: {
      problem_framing: "Problem framing",
      technical_mechanism: "Technical mechanism",
      methodology: "Methodology",
      results_numbers: "Results and numbers",
      roadmap_scalability: "Next steps",
      balanced: "Balanced",
    },
    phase: {
      hook: "Opening",
      context: "Context",
      core: "Core",
      evidence: "Evidence",
      implications: "Implications",
      close: "Close",
    },
  },
  ru: {
    mood: {
      warm_historical: "Тёплый исторический",
      clean_modern: "Чистый современный",
      bold_editorial: "Смелый редакционный",
      quiet_academic: "Сдержанный академический",
      vivid_scientific: "Яркий научный",
    },
    background: {
      dark: "Тёмный фон",
      light: "Светлый фон",
      gradient: "Градиент",
      texture: "Текстура",
      image: "Изображение",
    },
    audience: {
      school: "Школьники",
      undergraduate: "Студенты бакалавриата",
      graduate: "Магистранты",
      academic_conference: "Научная конференция",
      mixed_academic_industry: "Наука и индустрия",
      professional: "Специалисты",
      general_public: "Широкая аудитория",
    },
    emphasis: {
      problem_framing: "Постановка проблемы",
      technical_mechanism: "Технический механизм",
      methodology: "Методология",
      results_numbers: "Результаты и цифры",
      roadmap_scalability: "Следующие шаги",
      balanced: "Сбалансированный",
    },
    phase: {
      hook: "Вступление",
      context: "Контекст",
      core: "Основная часть",
      evidence: "Доказательства",
      implications: "Выводы",
      close: "Завершение",
    },
  },
  uz: {
    mood: {
      warm_historical: "Iliq, tarixiy",
      clean_modern: "Toza, zamonaviy",
      bold_editorial: "Qat’iy, jurnal uslubi",
      quiet_academic: "Vazmin, akademik",
      vivid_scientific: "Yorqin, ilmiy",
    },
    background: {
      dark: "To‘q fon",
      light: "Yorug‘ fon",
      gradient: "Gradient",
      texture: "Tekstura",
      image: "Rasm",
    },
    audience: {
      school: "Maktab o‘quvchilari",
      undergraduate: "Bakalavr talabalari",
      graduate: "Magistratura talabalari",
      academic_conference: "Akademik konferensiya",
      mixed_academic_industry: "Akademik va sanoat aralash",
      professional: "Mutaxassislar",
      general_public: "Keng jamoatchilik",
    },
    emphasis: {
      problem_framing: "Muammoni shakllantirish",
      technical_mechanism: "Texnik mexanizm",
      methodology: "Metodologiya",
      results_numbers: "Natijalar va raqamlar",
      roadmap_scalability: "Keyingi qadamlar",
      balanced: "Muvozanatli",
    },
    phase: {
      hook: "Ochilish",
      context: "Kontekst",
      core: "Asosiy qism",
      evidence: "Dalillar",
      implications: "Oqibatlar",
      close: "Yakun",
    },
  },
} satisfies Record<Locale, Record<string, Record<string, string>>>;

function label(
  group: keyof (typeof VOCABULARY)["uz"],
  value: string,
  locale: Locale,
): string {
  const values = VOCABULARY[locale][group] as Record<string, string>;
  return values[value] ?? value;
}

export const moodLabel = (v: string, locale: Locale = "uz") =>
  label("mood", v, locale);
export const backgroundLabel = (v: string, locale: Locale = "uz") =>
  label("background", v, locale);
export const audienceLabel = (v: string, locale: Locale = "uz") =>
  label("audience", v, locale);
export const emphasisLabel = (v: string, locale: Locale = "uz") =>
  label("emphasis", v, locale);
export const phaseLabel = (v: string, locale: Locale = "uz") =>
  label("phase", v, locale);

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
export function decidedFor(
  view: DecisionsView,
  locale: Locale = "uz",
): DecidedFact[] {
  const copy = {
    en: {
      audience: "Audience",
      duration: "Duration",
      minutes: "minutes",
      emphasis: "Emphasis",
      interactive: "Interactive",
      yes: "Yes",
      no: "No",
      slides: "Slides",
    },
    ru: {
      audience: "Аудитория",
      duration: "Длительность",
      minutes: "минут",
      emphasis: "Акцент",
      interactive: "Интерактив",
      yes: "Да",
      no: "Нет",
      slides: "Слайды",
    },
    uz: {
      audience: "Auditoriya",
      duration: "Davomiylik",
      minutes: "daqiqa",
      emphasis: "Urg‘u",
      interactive: "Interaktiv",
      yes: "Bor",
      no: "Yo‘q",
      slides: "Slaydlar",
    },
  }[locale];
  return [
    { label: copy.audience, value: audienceLabel(view.audience, locale) },
    {
      label: copy.duration,
      value: `${view.talk_duration_minutes} ${copy.minutes}`,
    },
    {
      label: copy.emphasis,
      value: emphasisLabel(view.narrative_emphasis, locale),
    },
    {
      label: copy.interactive,
      value: view.include_interactive ? copy.yes : copy.no,
    },
    {
      label: copy.slides,
      value:
        locale === "uz" ? `${view.slide_count} ta` : String(view.slide_count),
    },
  ];
}

/** The palette as swatches — a hex string is not a colour to a reader. */
export function swatches(
  view: DecisionsView,
  locale: Locale = "uz",
): Array<{ name: string; hex: string }> {
  const names = {
    en: ["Background", "Surface", "Text", "Accent"],
    ru: ["Фон", "Поверхность", "Текст", "Акцент"],
    uz: ["Fon", "Yuza", "Matn", "Urg‘u"],
  }[locale];
  return [
    { name: names[0], hex: view.palette.background },
    { name: names[1], hex: view.palette.surface },
    { name: names[2], hex: view.palette.text },
    { name: names[3], hex: view.palette.accent },
  ];
}

/** True when the deck predates the binding planner and has no argument to show. */
export function hasArgument(view: DecisionsView): boolean {
  return view.thesis !== null && view.sections.length > 0;
}
