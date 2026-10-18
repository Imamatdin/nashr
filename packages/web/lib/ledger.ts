// The credit ledger, turned into sentences.
//
// Two audit rows meet here. G8: the balance existed only inside a 402 refusal,
// so a user could never see what they had or what the product had done with
// it. G24: every web source upload grants a free credit and the user was never
// told — SPEC §3.6 is explicit that the BENEFIT leads and the credit is
// mentioned second ("Javobingiz tufayli muhokama bo'limi kuchaydi … va 1 ta
// bepul kredit qo'shildi"), which is impossible when nothing is rendered at all.
//
// IMPORTANT — what `reason` actually contains. `CreditLedger._insert`
// (packages/platform/credits.py) writes `reason = _ACTION_TO_REASON[action]`,
// so the DETAILED reason a caller passes ("source_upload", the worker's refund
// sentence) is dropped before the row is stored. A persisted grant_free row
// therefore arrives here as `reason: "learning_reward"`, and a refund as
// `reason: "refund"`. Everything below keys on `action`; `reason` only ever
// REFINES the copy when it happens to carry the finer value.

import type { LedgerEntryView } from "./api";
import type { Locale } from "./locale";
import { soum } from "./packages";

export type LedgerTone = "reward" | "paid" | "spend" | "refund" | "neutral";

export interface LedgerRow {
  /** What happened, in one noun phrase. */
  label: string;
  /** The sentence under the label, when the row has something to explain. */
  note: string | null;
  tone: LedgerTone;
  /** Signed, formatted, ready to render. */
  amount: string;
  /** dd.mm.yyyy — a filing date, matching the folio. */
  date: string;
  /** Where the row happened, when it belongs to a project. */
  href: string | null;
}

/**
 * `+5 000 so'm` / `−10 000 so'm`.
 *
 * The sign is explicit and always leads: a ledger where a spend and a refund
 * differ only by a character somewhere inside the number is unreadable.
 */
export function signedSoum(amount: number): string {
  const sign = amount < 0 ? "−" : "+";
  return `${sign}${soum(Math.abs(amount))}`;
}

/** dd.mm.yyyy, or an em dash when the timestamp is unusable. */
export function ledgerDate(value: string | null): string {
  if (!value) return "—";
  const when = new Date(value);
  if (Number.isNaN(when.getTime())) return "—";
  const pad = (part: number) => part.toString().padStart(2, "0");
  return `${pad(when.getDate())}.${pad(when.getMonth() + 1)}.${when.getFullYear()}`;
}

const ACTION_LABEL: Record<Locale, Record<string, string>> = {
  en: {
    grant_free: "Research reward",
    grant_paid: "Payment received",
    deduct_article: "Article created",
    deduct_presentation: "Presentation created",
    refund: "Credit refunded",
  },
  ru: {
    grant_free: "Награда за исследование",
    grant_paid: "Платёж получен",
    deduct_article: "Статья создана",
    deduct_presentation: "Презентация создана",
    refund: "Средства возвращены",
  },
  uz: {
    grant_free: "O‘rganish mukofoti",
    grant_paid: "To‘lov qabul qilindi",
    deduct_article: "Maqola yaratildi",
    deduct_presentation: "Taqdimot yaratildi",
    refund: "Kredit qaytarildi",
  },
  kaa: {
    grant_free: "Úyreniw sıylıǵı",
    grant_paid: "Tólem qabıl etildi",
    deduct_article: "Maqala jaratıldı",
    deduct_presentation: "Prezentaciya jaratıldı",
    refund: "Kredit qaytarıldı",
  },
};

const ACTION_TONE: Record<string, LedgerTone> = {
  grant_free: "reward",
  grant_paid: "paid",
  deduct_article: "spend",
  deduct_presentation: "spend",
  refund: "refund",
};

/**
 * The reward sentence (G24): what the user's work did for the output, then the
 * credit.
 *
 * Keyed on the fine-grained `FreeCreditsReason` when the row carries one. It
 * usually does not — see the module note — so `learning_reward` and anything
 * else fall to a line that is true of every path that grants a free credit:
 * they are all research actions that strengthen the evidence base. Nothing
 * here promises an incentive the product does not have; the caps live in
 * `GET /pricing` and are the page's business, not this sentence's.
 */
export function rewardCopy(
  entry: LedgerEntryView,
  locale: Locale = "uz",
): string {
  const amount = soum(Math.abs(entry.amount));
  if (locale === "en") {
    const credit = `and ${amount} in free credit was added`;
    const action = {
      source_upload: `Your source strengthened the evidence base, ${credit}.`,
      interview_answer: `Your answer made the work fit the topic more precisely, ${credit}.`,
      contradiction_explain: `Your explanation resolved a source conflict and strengthened the analysis, ${credit}.`,
      daily_bonus: `Daily bonus: ${credit}.`,
    } as const;
    return (
      action[entry.reason as keyof typeof action] ??
      `Your research strengthened the evidence base, ${credit}.`
    );
  }
  if (locale === "ru") {
    const credit = `и начислено ${amount} бесплатного кредита`;
    const action = {
      source_upload: `Ваш источник укрепил доказательную базу, ${credit}.`,
      interview_answer: `Ваш ответ помог точнее адаптировать работу к теме, ${credit}.`,
      contradiction_explain: `Вы объяснили противоречие между источниками и усилили анализ, ${credit}.`,
      daily_bonus: `Ежедневный бонус: ${credit}.`,
    } as const;
    return (
      action[entry.reason as keyof typeof action] ??
      `Ваше исследование укрепило доказательную базу, ${credit}.`
    );
  }
  if (locale === "kaa") {
    const credit = `hám ${amount} bepul kredit qosıldı`;
    switch (entry.reason) {
      case "source_upload":
        return `Júklegen deregińiz jumıstıń dálil bazasın kúsheytti — ${credit}.`;
      case "interview_answer":
        return `Juwabıńız arqalı jumıs temańızǵa anıǵıraq sáykeslesti — ${credit}.`;
      case "contradiction_explain":
        return `Derekler arasındaǵı qarama-qarsılıqtı túsindirdińiz, talqılaw kúsheydi — ${credit}.`;
      case "daily_bonus":
        return `Kúnlik bonus — ${credit}.`;
      default:
        return `Izertlew jumısıńız jumıstıń dálil bazasın kúsheytti — ${credit}.`;
    }
  }
  const credit = `va ${amount} bepul kredit qo‘shildi`;
  switch (entry.reason) {
    case "source_upload":
      return `Yuklagan manbangiz ishning dalil bazasini kuchaytirdi — ${credit}.`;
    case "interview_answer":
      return `Javobingiz tufayli ish sizning mavzuyingizga aniqroq moslashdi — ${credit}.`;
    case "contradiction_explain":
      return `Manbalar orasidagi ziddiyatni izohladingiz, tahlil kuchaydi — ${credit}.`;
    case "daily_bonus":
      return `Kunlik bonus — ${credit}.`;
    default:
      return `Tadqiqot ishingiz ishning dalil bazasini kuchaytirdi — ${credit}.`;
  }
}

/** The sentence under a spend or a refund, when there is one worth saying. */
function noteFor(entry: LedgerEntryView, locale: Locale): string | null {
  if (entry.action === "grant_free") return rewardCopy(entry, locale);
  if (entry.action === "refund") {
    if (locale === "en") {
      return entry.generation_job_id !== null
        ? "Generation failed, so the charged credit was returned to your balance."
        : "The charged credit was returned to your balance.";
    }
    if (locale === "ru") {
      return entry.generation_job_id !== null
        ? "Генерация не завершилась, поэтому списанные средства вернулись на баланс."
        : "Списанные средства вернулись на баланс.";
    }
    if (locale === "kaa") {
      return entry.generation_job_id !== null
        ? "Generaciya sátsiz tamamlandı — alınǵan aqsha esabıńızǵa qaytarıldı."
        : "Alınǵan aqsha esabıńızǵa qaytarıldı.";
    }
    return entry.generation_job_id !== null
      ? "Generatsiya muvaffaqiyatsiz tugadi — yechilgan mablag‘ hisobingizga qaytarildi."
      : "Yechilgan mablag‘ hisobingizga qaytarildi.";
  }
  return null;
}

/**
 * One wire row → one rendered row.
 *
 * An action this build has never seen still produces human copy: the ledger is
 * append-only and a future action value must not blank a user's history.
 */
export function describeLedgerEntry(
  entry: LedgerEntryView,
  locale: Locale = "uz",
): LedgerRow {
  return {
    label:
      ACTION_LABEL[locale][entry.action] ??
      (locale === "en"
        ? "Balance activity"
        : locale === "ru"
          ? "Операция по балансу"
          : locale === "kaa"
            ? "Esap operaciyası"
            : "Hisob amaliyoti"),
    note: noteFor(entry, locale),
    tone: ACTION_TONE[entry.action] ?? "neutral",
    amount: signedSoum(entry.amount),
    date: ledgerDate(entry.created_at),
    href: entry.project_id !== null ? `/projects/${entry.project_id}` : null,
  };
}
