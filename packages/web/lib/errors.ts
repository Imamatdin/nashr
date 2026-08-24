// Every user-facing failure in the app resolves through here.
//
// The coherence audit's §4 ledger found 22 sites printing machine strings at
// the user: `Error: API 500: psycopg.errors.UndefinedColumn…`, pydantic
// validation arrays, PostgREST sentences, raw Python exceptions. The rule this
// module enforces is simple: a raw string never reaches a rendered surface.
// An unknown code still produces human copy — the machine detail moves into a
// collapsible "texnik tafsilot" the user can open but never has to read.
//
// Copy is Uzbek, shaped as one flat catalog so a future locale is a second
// file and a lookup, not a refactor. Building the i18n layer itself is out of
// scope for this run (G27).

import { ApiError } from "./api";
import { STEP_LABELS } from "./steps";

export type ErrorTone = "error" | "warn" | "info";

export interface ErrorAction {
  /** Button copy. */
  label: string;
  /** What the surface should do. Pages map these to their own handlers. */
  kind: "retry" | "login" | "topup" | "back" | "reload" | "dismiss";
}

export interface FriendlyError {
  title: string;
  message: string;
  tone: ErrorTone;
  action?: ErrorAction;
  /** The machine string, for the collapsible detail. Never rendered inline. */
  detail?: string;
  /** The reason code we matched, or null when we fell through to generic. */
  reason: string | null;
}

const RETRY: ErrorAction = { label: "Qayta urinish", kind: "retry" };
const LOGIN: ErrorAction = { label: "Qaytadan kirish", kind: "login" };
const RELOAD: ErrorAction = { label: "Sahifani yangilash", kind: "reload" };
const BACK: ErrorAction = { label: "Loyihalarga qaytish", kind: "back" };

interface Entry {
  title: string;
  message: string;
  tone?: ErrorTone;
  action?: ErrorAction;
}

// Keyed by the API's machine reason code. The API's job is a stable code; this
// is the only place that decides what a human is told about it.
const CATALOG: Record<string, Entry> = {
  // --- money ---------------------------------------------------------------
  insufficient_balance: {
    title: "Kredit yetarli emas",
    // The balance/required numbers are spliced in by creditCopy(): a fixed
    // sentence that hides the actual shortfall is what made the 402 a
    // dead end in the first place.
    message: "Bu paketni boshlash uchun hisobingizda yetarli kredit yo‘q.",
    action: { label: "Telegram botda to‘ldirish", kind: "topup" },
  },

  // --- limits --------------------------------------------------------------
  rate_limited: {
    title: "Limitga yetdingiz",
    message: "Biroz kuting — limit yangilanadi.",
  },

  // --- the brain / editing -------------------------------------------------
  brain_busy: {
    title: "Hozir band",
    message:
      "Taqdimot ustida ish ketmoqda. Tugashini kuting — keyin yana yozishingiz mumkin.",
    tone: "info",
  },
  session_not_ready: {
    title: "Tahrirlash hali mumkin emas",
    message:
      "Suhbat taqdimot tayyor bo‘lgandan keyin ochiladi — u tayyor slaydlar ustida ishlaydi.",
    tone: "info",
  },
  fixes_exhausted: {
    title: "Tahrirlar tugadi",
    message: "Bu paketdagi tahrirlar soni tugadi.",
    tone: "info",
  },
  no_pending_action: {
    title: "Tasdiqlanadigan o‘zgarish yo‘q",
    message: "Bu o‘zgarish allaqachon qo‘llangan yoki bekor qilingan.",
    tone: "info",
  },
  edit_not_queued: {
    title: "Tahrir boshlanmadi",
    message: "Tahrirni navbatga qo‘yib bo‘lmadi. Suhbat saqlanib qoldi.",
    action: RETRY,
  },

  // --- sources / interview -------------------------------------------------
  sources_not_ready: {
    // A designed state, not a failure: on a first run the sources have not been
    // processed yet, so there are no questions to ask. The composer routes
    // this into "Decide for me" instead of showing an error at all.
    title: "Savollar hali tayyor emas",
    message:
      "Manbalar birinchi generatsiyada o‘qiladi. Hozircha biz o‘zimiz qaror qilamiz — keyingi safar savollar bilan aniqlashtirasiz.",
    tone: "info",
  },
  unregistered_source: {
    title: "Manba topilmadi",
    message: "Bu fayl ro‘yxatdan o‘tmagan. Qaytadan biriktiring.",
  },
  file_too_large: {
    title: "Fayl juda katta",
    message: "Har bir fayl 20 MB dan oshmasligi kerak.",
  },
  file_type_not_allowed: {
    title: "Bu turdagi fayl qabul qilinmaydi",
    message: "PDF, DOCX, PPTX, XLSX, rasm yoki matn fayli yuklang.",
  },
  r2_upload_failed: {
    title: "Fayl yuklanmadi",
    message: "Ulanish uzildi shekilli. Faylni qayta yuklang.",
    action: RETRY,
  },

  // --- identity ------------------------------------------------------------
  missing_bearer_token: {
    title: "Sessiya tugadi",
    message: "Xavfsizlik uchun sessiya yopildi. Qaytadan kiring.",
    action: LOGIN,
  },
  expired: {
    title: "Sessiya muddati tugadi",
    message: "Qaytadan kirsangiz, shu yerdan davom etasiz.",
    action: LOGIN,
  },
  bad_signature: {
    title: "Sessiya yaroqsiz",
    message: "Qaytadan kiring.",
    action: LOGIN,
  },
  malformed: {
    title: "Sessiya yaroqsiz",
    message: "Qaytadan kiring.",
    action: LOGIN,
  },
  wrong_issuer: {
    title: "Sessiya yaroqsiz",
    message: "Qaytadan kiring.",
    action: LOGIN,
  },
  initdata_expired: {
    title: "Telegram havolasi eskirdi",
    message: "Botga qaytib, havolani qaytadan oching.",
  },
  telegram_auth_backend_down: {
    title: "Kirish vaqtincha ishlamayapti",
    message: "Bir necha daqiqadan so‘ng qayta urinib ko‘ring.",
    action: RETRY,
  },
  server_missing_jwt_secret: {
    title: "Xizmat sozlanmagan",
    message: "Bu bizning tomondagi nosozlik. Tez orada tuzatamiz.",
  },

  // --- not found -----------------------------------------------------------
  project_not_found: {
    title: "Loyiha topilmadi",
    message: "Bu loyiha o‘chirilgan yoki sizga tegishli emas.",
    action: BACK,
  },
  job_not_found: {
    title: "Generatsiya topilmadi",
    message: "Bu loyiha uchun hali generatsiya boshlanmagan.",
    tone: "info",
  },
  deck_not_ready: {
    title: "Taqdimot hali tayyor emas",
    message: "Fayllar tayyorlanmoqda — bir lahza.",
    tone: "info",
  },
  not_found: {
    title: "Havola ishlamaydi",
    message: "Havola noto‘g‘ri yoki egasi uni o‘chirgan.",
  },
};

/** Status-code fallbacks for responses with no reason we recognise. */
const BY_STATUS: Record<number, Entry> = {
  401: {
    title: "Sessiya tugadi",
    message: "Qaytadan kiring — shu yerdan davom etasiz.",
    action: LOGIN,
  },
  403: { title: "Ruxsat yo‘q", message: "Bu amalga sizda ruxsat yo‘q." },
  404: { title: "Topilmadi", message: "So‘ralgan narsa mavjud emas.", action: BACK },
  409: { title: "Hozir mumkin emas", message: "Holat o‘zgardi — sahifani yangilang.", tone: "info", action: RELOAD },
  413: { title: "Fayl juda katta", message: "Har bir fayl 20 MB dan oshmasligi kerak." },
  422: {
    title: "So‘rov qabul qilinmadi",
    message: "Ma’lumotlarni tekshirib, qayta yuboring.",
  },
  429: { title: "Limitga yetdingiz", message: "Biroz kuting — limit yangilanadi." },
  500: { title: "Xizmatda nosozlik", message: "Bu bizning tomondagi xato. Qayta urinib ko‘ring.", action: RETRY },
  502: { title: "Xizmat javob bermayapti", message: "Bir necha daqiqadan so‘ng urinib ko‘ring.", action: RETRY },
  503: { title: "Xizmat vaqtincha yopiq", message: "Bir necha daqiqadan so‘ng urinib ko‘ring.", action: RETRY },
};

const OFFLINE: Entry = {
  title: "Internet uzildi",
  message: "Ulanishni tekshiring — ma’lumot olinmadi.",
  action: RETRY,
};

const GENERIC: Entry = {
  title: "Nimadir xato ketdi",
  message: "Buni biz kutmagandik. Qayta urinib ko‘ring — takrorlansa, xabar bering.",
  action: RETRY,
};

/**
 * The API answers some failures with a JSON object in `detail`, which the
 * client stringifies. Pull the reason back out without letting a parse failure
 * become the user's problem.
 */
function structuredReason(raw: string): { reason: string | null; fields: Record<string, unknown> } {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return { reason: null, fields: {} };
    const fields = parsed as Record<string, unknown>;
    const reason = typeof fields.reason === "string" ? fields.reason : null;
    return { reason, fields };
  } catch {
    return { reason: null, fields: {} };
  }
}

/** The reason code an error carries, if any — for callers that branch on it. */
export function reasonOf(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const structured = structuredReason(error.reason);
  if (structured.reason) return structured.reason;
  // A bare-string detail (`project_not_found`) is itself the code. Anything
  // with whitespace is prose, not a code.
  return /^[a-z0-9_]+$/.test(error.reason) ? error.reason : null;
}

/** The structured fields the API sent alongside the reason (429 state, 402 balance). */
export function fieldsOf(error: unknown): Record<string, unknown> {
  if (!(error instanceof ApiError)) return {};
  return structuredReason(error.reason).fields;
}

/**
 * Map any thrown value to copy a person can act on.
 *
 * Never throws, never returns a machine string in `title` or `message`. The
 * raw text survives in `detail` so a support conversation can still get at it.
 */
export function describeError(error: unknown): FriendlyError {
  if (error instanceof ApiError) {
    const reason = reasonOf(error);
    const entry = (reason && CATALOG[reason]) || BY_STATUS[error.status] || GENERIC;
    return {
      title: entry.title,
      message: entry.message,
      tone: entry.tone ?? "error",
      action: entry.action,
      detail: `HTTP ${error.status} · ${error.reason}`,
      reason,
    };
  }

  // A fetch that never reached the server rejects with TypeError. Treating it
  // as a server fault would tell the user to blame us for their tunnel.
  if (error instanceof TypeError) {
    return { ...OFFLINE, tone: "error", detail: String(error), reason: "network" };
  }

  if (error instanceof DOMException && error.name === "AbortError") {
    return {
      title: "So‘rov juda uzoq davom etdi",
      message: "Javob kelmadi. Qayta urinib ko‘ring.",
      tone: "error",
      action: RETRY,
      detail: String(error),
      reason: "timeout",
    };
  }

  return { ...GENERIC, tone: "error", detail: String(error), reason: null };
}

/**
 * The 402 body carries the real numbers; a fixed sentence that omits them is
 * what made the money moment a dead end (G8). Falls back to the catalog copy
 * when the body is not the shape we expect.
 */
export function creditCopy(error: unknown, formatSum: (n: number) => string): FriendlyError {
  const base = describeError(error);
  const fields = fieldsOf(error);
  const balance = fields.balance;
  const required = fields.required;
  if (typeof balance !== "number" || typeof required !== "number") return base;
  return {
    ...base,
    message: `Hisobingizda ${formatSum(balance)}, bu paket uchun ${formatSum(
      required,
    )} kerak. Yetishmayapti: ${formatSum(Math.max(0, required - balance))}.`,
  };
}

/**
 * 429 copy that states WHEN, instead of asserting "ertaga" for a cap that may
 * reset in twenty minutes, and names the per-IP case so a campus network does
 * not read as the user's own fault (G32).
 */
export function rateLimitCopy(error: unknown): FriendlyError {
  const base = describeError(error);
  const fields = fieldsOf(error);
  const resetsAt = typeof fields.resets_at === "string" ? new Date(fields.resets_at) : null;
  const scope = fields.scope === "ip" ? "ip" : "user";
  const limit = typeof fields.limit === "number" ? fields.limit : null;

  const when =
    resetsAt && Number.isFinite(resetsAt.getTime()) ? ` Limit ${formatReset(resetsAt)} yangilanadi.` : "";
  const who =
    scope === "ip"
      ? " Bu cheklov shu tarmoqdagi barcha foydalanuvchilarga tegishli (masalan, bitta Wi-Fi)."
      : "";
  const howMany = limit !== null ? ` Kunlik chek: ${limit} ta.` : "";

  return { ...base, message: `${base.message}${howMany}${when}${who}`.trim() };
}

function formatReset(at: Date): string {
  const minutes = Math.round((at.getTime() - Date.now()) / 60_000);
  if (minutes <= 1) return "bir daqiqada";
  if (minutes < 60) return `${minutes} daqiqada`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} soatda`;
  return at.toLocaleDateString("uz-UZ", { day: "numeric", month: "long" });
}

/**
 * Copy for a failed generation, from the worker's own `error_message`.
 *
 * The worker writes `"{step}: {ExceptionType}: {detail}"`
 * (scripts/worker_run_job.py). Rendering that verbatim is the §4 ledger's row 8
 * — a raw Python exception shown to a teacher. But discarding it and printing
 * "something went wrong" throws away the one genuinely useful fact in it: WHICH
 * STEP stopped. A run that died choosing a design direction is a different
 * event to one that died reading the sources, and the user can act on the
 * difference (a scanned PDF, an unsupported topic).
 *
 * So the step is recovered and named in human terms; everything after it goes
 * to the collapsible detail.
 */
export function describeJobFailure(errorMessage: string | null): FriendlyError {
  const base: FriendlyError = {
    title: "Generatsiya to‘xtadi",
    message: "Jarayon tugamadi.",
    tone: "error",
    detail: errorMessage ?? undefined,
    reason: "job_failed",
  };
  if (!errorMessage) {
    return { ...base, message: "Jarayon tugamadi. Sababi qayd etilmagan." };
  }

  const separator = errorMessage.indexOf(":");
  const stepKey = separator === -1 ? errorMessage.trim() : errorMessage.slice(0, separator).trim();
  const known = STEP_LABELS.find((entry) => entry.key === stepKey);
  if (known) {
    return {
      ...base,
      message: `«${known.label}» bosqichida to‘xtadi.`,
    };
  }
  // An unrecognised step name is still not an excuse to print the exception.
  return base;
}
