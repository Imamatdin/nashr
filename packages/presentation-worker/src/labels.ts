/**
 * Localized labels for user-facing presentation text.
 *
 * Every UI string that the presentation surfaces (navigation chrome,
 * interactive prompts, section headings like "Key Takeaways") comes
 * through `getLabels(deck.language)`. Hardcoded English (or anything
 * else) in a layout function is a localization bug — the user's
 * deck.language is the single source of truth.
 *
 * Supported languages:
 *   - uz  Uzbek (Latin)
 *   - ru  Russian
 *   - en  English
 *   - kaa Karakalpak (Latin) — DISTINCT from Uzbek. The Ag'artıwshılıq
 *         golden reference is Karakalpak. "Kelesi" (kaa) ≠ "Keyingi" (uz).
 *
 * Looking up an unknown language falls back to English; the language
 * value passed in is permissive (any string) so the system stays
 * robust if the wire format ever picks up a new code.
 */

export type SupportedLanguage = 'uz' | 'ru' | 'en';

export interface NavigationLabels {
  next: string;
  back: string;
  /** Template with `{current}` and `{total}` placeholders. */
  slideOf: string;
}

export interface InteractiveLabels {
  correct: string;
  wrong: string;
  tryAgain: string;
  showAnswer: string;
  hint: string;
  checkPairs: string;
  fillBlank: string;
  trueLabel: string;
  falseLabel: string;
  selfAssess: string;
}

export interface ContentLabels {
  keyTakeaways: string;
  questions: string;
  tasks: string;
  research: string;
  essay: string;
  references: string;
  credits: string;
  thankYou: string;
}

export interface PresentationLabels {
  nav: NavigationLabels;
  interactive: InteractiveLabels;
  content: ContentLabels;
}

const LABELS: Record<SupportedLanguage, PresentationLabels> = {
  uz: {
    nav: {
      next: "Keyingi",
      back: "Orqaga",
      slideOf: "{current} / {total}",
    },
    interactive: {
      correct: "To'g'ri",
      wrong: "Noto'g'ri",
      tryAgain: "Qayta urinib ko'ring",
      showAnswer: "Javobni ko'rsatish",
      hint: "Maslahat",
      checkPairs: "Juftlarni tekshirish",
      fillBlank: "Bo'sh joyni to'ldiring",
      trueLabel: "To'g'ri",
      falseLabel: "Noto'g'ri",
      selfAssess: "O'zingizni baholang: nimani yaxshi bilasiz, nimani qayta o'qiysiz?",
    },
    content: {
      keyTakeaways: "Asosiy xulosalar",
      questions: "Savollar",
      tasks: "Topshiriqlar",
      research: "Tadqiqot",
      essay: "Esse",
      references: "Manbalar",
      credits: "Mualliflar",
      thankYou: "Rahmat",
    },
  },
  ru: {
    nav: {
      next: "Далее",
      back: "Назад",
      slideOf: "{current} / {total}",
    },
    interactive: {
      correct: "Правильно",
      wrong: "Неверно",
      tryAgain: "Попробуйте снова",
      showAnswer: "Показать ответ",
      hint: "Подсказка",
      checkPairs: "Проверить пары",
      fillBlank: "Заполните пропуск",
      trueLabel: "Верно",
      falseLabel: "Неверно",
      selfAssess: "Оцените себя: что знаете хорошо, что стоит повторить?",
    },
    content: {
      keyTakeaways: "Ключевые выводы",
      questions: "Вопросы",
      tasks: "Задания",
      research: "Исследование",
      essay: "Эссе",
      references: "Источники",
      credits: "Авторы",
      thankYou: "Спасибо",
    },
  },
  en: {
    nav: {
      next: "Next",
      back: "Back",
      slideOf: "{current} / {total}",
    },
    interactive: {
      correct: "Correct",
      wrong: "Wrong",
      tryAgain: "Try again",
      showAnswer: "Show answer",
      hint: "Hint",
      checkPairs: "Check pairs",
      fillBlank: "Fill in the blank",
      trueLabel: "True",
      falseLabel: "False",
      selfAssess: "Assess yourself: what do you know well, what should you review?",
    },
    content: {
      keyTakeaways: "Key Takeaways",
      questions: "Questions",
      tasks: "Tasks",
      research: "Research",
      essay: "Essay",
      references: "References",
      credits: "Credits",
      thankYou: "Thank You",
    },
  },
};

/**
 * Karakalpak (kaa) labels.
 *
 * Karakalpak is a distinct Turkic language with its own Latin
 * orthography. It is the language of the Ag'artıwshılıq golden
 * reference deck. Although Karakalpak shares some vocabulary with
 * Uzbek, the navigation and feedback labels diverge:
 *   - "Kelesi" / "Artqa" (kaa) vs. "Keyingi" / "Orqaga" (uz)
 *   - "Dúrıs" / "Qáte"  (kaa) vs. "To'g'ri" / "Noto'g'ri" (uz)
 *
 * Stored as its own constant rather than a member of `LABELS` because
 * `SupportedLanguage` intentionally lists only the three Tier-1 codes
 * (uz/ru/en). Karakalpak is dispatched on the language prefix before
 * the standard lookup runs.
 */
const LABELS_KAA: PresentationLabels = {
  nav: {
    next: "Kelesi",
    back: "Artqa",
    slideOf: "{current} / {total}",
  },
  interactive: {
    correct: "Dúrıs",
    wrong: "Qáte",
    tryAgain: "Qayta urınıp kór",
    showAnswer: "Jauapdı kórset",
    hint: "Kenes",
    checkPairs: "Juplardı tekser",
    fillBlank: "Bos orındı toltırıń",
    trueLabel: "Dúrıs",
    falseLabel: "Qáte",
    selfAssess: "Ózińdi bahala: neni jaqsı bilesiń, neni qayta oqıysıń?",
  },
  content: {
    keyTakeaways: "Tiykarǵı juwmaqlar",
    questions: "Sorawlar",
    tasks: "Tapsırmalar",
    research: "Izertlew",
    essay: "Esse",
    references: "Derekler",
    credits: "Avtorlar",
    thankYou: "Raxmet",
  },
};

/**
 * Return the label set for the deck's language. Karakalpak (kaa) is
 * checked first because its two-letter prefix ("ka") otherwise collides
 * with no standard ISO 639-1 code we care about, and falling back to
 * the prefix lookup would mis-route it to English.
 *
 * Any language string that doesn't match falls back to English so the
 * deck still renders rather than throwing at the renderer boundary.
 */
export function getLabels(language: string): PresentationLabels {
  const normalized = language.trim().toLowerCase();
  if (normalized.startsWith('kaa')) {
    return LABELS_KAA;
  }
  const code = normalized.slice(0, 2);
  if (code === 'uz' || code === 'ru' || code === 'en') {
    return LABELS[code];
  }
  return LABELS.en;
}
