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
import type { Locale } from "./locale";
import { stepLabels } from "./steps";

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
  404: {
    title: "Topilmadi",
    message: "So‘ralgan narsa mavjud emas.",
    action: BACK,
  },
  409: {
    title: "Hozir mumkin emas",
    message: "Holat o‘zgardi — sahifani yangilang.",
    tone: "info",
    action: RELOAD,
  },
  413: {
    title: "Fayl juda katta",
    message: "Har bir fayl 20 MB dan oshmasligi kerak.",
  },
  422: {
    title: "So‘rov qabul qilinmadi",
    message: "Ma’lumotlarni tekshirib, qayta yuboring.",
  },
  429: {
    title: "Limitga yetdingiz",
    message: "Biroz kuting — limit yangilanadi.",
  },
  500: {
    title: "Xizmatda nosozlik",
    message: "Bu bizning tomondagi xato. Qayta urinib ko‘ring.",
    action: RETRY,
  },
  502: {
    title: "Xizmat javob bermayapti",
    message: "Bir necha daqiqadan so‘ng urinib ko‘ring.",
    action: RETRY,
  },
  503: {
    title: "Xizmat vaqtincha yopiq",
    message: "Bir necha daqiqadan so‘ng urinib ko‘ring.",
    action: RETRY,
  },
};

const OFFLINE: Entry = {
  title: "Internet uzildi",
  message: "Ulanishni tekshiring — ma’lumot olinmadi.",
  action: RETRY,
};

const GENERIC: Entry = {
  title: "Nimadir xato ketdi",
  message:
    "Buni biz kutmagandik. Qayta urinib ko‘ring — takrorlansa, xabar bering.",
  action: RETRY,
};

const ERROR_COPY = {
  en: {
    actions: {
      retry: "Try again",
      login: "Sign in again",
      topup: "Add credit in Telegram",
      back: "Back to projects",
      reload: "Reload page",
      dismiss: "Dismiss",
    },
    reasons: {
      insufficient_balance: [
        "Not enough credit",
        "Your balance is too low to start this package.",
      ],
      rate_limited: [
        "Limit reached",
        "Wait a little while for the limit to reset.",
      ],
      brain_busy: [
        "Presentation is busy",
        "An edit is already running. Wait for it to finish, then try again.",
      ],
      session_not_ready: [
        "Editing is not ready",
        "Chat opens after the presentation is ready and works on its completed slides.",
      ],
      fixes_exhausted: [
        "No edits remaining",
        "You have used all edits included in this package.",
      ],
      no_pending_action: [
        "Nothing to approve",
        "This change was already applied or dismissed.",
      ],
      edit_not_queued: [
        "Edit did not start",
        "The edit could not be queued. Your conversation is still saved.",
      ],
      sources_not_ready: [
        "Questions are not ready",
        "Sources are read during the first generation. Nashr will choose sensible defaults now and ask source-specific questions next time.",
      ],
      unregistered_source: [
        "Source not found",
        "This file was not registered. Attach it again.",
      ],
      file_too_large: [
        "File is too large",
        "Each file must be 20 MB or smaller.",
      ],
      file_type_not_allowed: [
        "File type is not supported",
        "Upload a PDF, DOCX, PPTX, XLSX, image, or text file.",
      ],
      r2_upload_failed: [
        "Upload failed",
        "The connection may have dropped. Upload the file again.",
      ],
      missing_bearer_token: [
        "Session ended",
        "For your security, the session was closed. Sign in again.",
      ],
      expired: [
        "Session expired",
        "Sign in again to continue where you left off.",
      ],
      bad_signature: ["Invalid session", "Sign in again."],
      malformed: ["Invalid session", "Sign in again."],
      wrong_issuer: ["Invalid session", "Sign in again."],
      initdata_expired: [
        "Telegram link expired",
        "Return to the bot and open a new link.",
      ],
      telegram_auth_backend_down: [
        "Sign-in is temporarily unavailable",
        "Try again in a few minutes.",
      ],
      server_missing_jwt_secret: [
        "Service is not configured",
        "This is a problem on our side. We are fixing it.",
      ],
      project_not_found: [
        "Project not found",
        "This project was deleted or does not belong to you.",
      ],
      job_not_found: [
        "Generation not found",
        "No generation has started for this project yet.",
      ],
      deck_not_ready: [
        "Presentation is not ready",
        "The files are still being prepared.",
      ],
      not_found: [
        "Link is unavailable",
        "The link is incorrect or its owner disabled it.",
      ],
    },
    statuses: {
      401: ["Session ended", "Sign in again to continue where you left off."],
      403: ["Access denied", "You do not have permission to do this."],
      404: ["Not found", "The requested item does not exist."],
      409: ["State changed", "Reload the page and try again."],
      413: ["File is too large", "Each file must be 20 MB or smaller."],
      422: [
        "Request was not accepted",
        "Check the information and submit it again.",
      ],
      429: ["Limit reached", "Wait a little while for the limit to reset."],
      500: ["Service error", "This is a problem on our side. Try again."],
      502: ["Service is not responding", "Try again in a few minutes."],
      503: [
        "Service is temporarily unavailable",
        "Try again in a few minutes.",
      ],
    },
    offline: [
      "You are offline",
      "Check your connection. No data was received.",
    ],
    generic: [
      "Something went wrong",
      "Try again. If it keeps happening, let us know.",
    ],
    timeout: ["The request took too long", "No response arrived. Try again."],
    jobFailed: "Generation stopped",
    jobIncomplete: "The process did not finish.",
    jobNoReason: "The process did not finish and no reason was recorded.",
    stoppedAt: (step: string) => `Stopped during “${step}”.`,
    balance: (balance: string, required: string, missing: string) =>
      `Your balance is ${balance}. This package requires ${required}; ${missing} is missing.`,
    resetIn: "The limit resets",
    dailyLimit: "Daily limit",
    sharedNetwork:
      "This limit applies to everyone on the same network, such as one Wi-Fi connection.",
  },
  ru: {
    actions: {
      retry: "Повторить",
      login: "Войти снова",
      topup: "Пополнить в Telegram",
      back: "Назад к проектам",
      reload: "Обновить страницу",
      dismiss: "Закрыть",
    },
    reasons: {
      insufficient_balance: [
        "Недостаточно средств",
        "На балансе недостаточно средств для запуска этого пакета.",
      ],
      rate_limited: [
        "Лимит исчерпан",
        "Подождите немного, пока лимит обновится.",
      ],
      brain_busy: [
        "Презентация занята",
        "Уже выполняется другая правка. Дождитесь её завершения.",
      ],
      session_not_ready: [
        "Редактирование пока недоступно",
        "Чат откроется после подготовки презентации и будет работать с готовыми слайдами.",
      ],
      fixes_exhausted: [
        "Правки закончились",
        "Вы использовали все правки в этом пакете.",
      ],
      no_pending_action: [
        "Нечего подтверждать",
        "Это изменение уже применено или отменено.",
      ],
      edit_not_queued: [
        "Правка не запустилась",
        "Не удалось поставить правку в очередь. Переписка сохранена.",
      ],
      sources_not_ready: [
        "Вопросы ещё не готовы",
        "Источники читаются при первой генерации. Сейчас Nashr выберет разумные настройки, а в следующий раз задаст вопросы по источникам.",
      ],
      unregistered_source: [
        "Источник не найден",
        "Файл не зарегистрирован. Прикрепите его снова.",
      ],
      file_too_large: [
        "Файл слишком большой",
        "Размер каждого файла не должен превышать 20 МБ.",
      ],
      file_type_not_allowed: [
        "Тип файла не поддерживается",
        "Загрузите PDF, DOCX, PPTX, XLSX, изображение или текстовый файл.",
      ],
      r2_upload_failed: [
        "Файл не загрузился",
        "Возможно, соединение прервалось. Загрузите файл снова.",
      ],
      missing_bearer_token: [
        "Сессия завершена",
        "Для безопасности сессия была закрыта. Войдите снова.",
      ],
      expired: [
        "Сессия истекла",
        "Войдите снова, чтобы продолжить с этого места.",
      ],
      bad_signature: ["Недействительная сессия", "Войдите снова."],
      malformed: ["Недействительная сессия", "Войдите снова."],
      wrong_issuer: ["Недействительная сессия", "Войдите снова."],
      initdata_expired: [
        "Ссылка Telegram устарела",
        "Вернитесь в бота и откройте новую ссылку.",
      ],
      telegram_auth_backend_down: [
        "Вход временно недоступен",
        "Повторите попытку через несколько минут.",
      ],
      server_missing_jwt_secret: [
        "Сервис не настроен",
        "Проблема на нашей стороне. Мы её исправляем.",
      ],
      project_not_found: [
        "Проект не найден",
        "Проект удалён или не принадлежит вам.",
      ],
      job_not_found: [
        "Генерация не найдена",
        "Для этого проекта генерация ещё не запускалась.",
      ],
      deck_not_ready: [
        "Презентация ещё не готова",
        "Файлы всё ещё подготавливаются.",
      ],
      not_found: [
        "Ссылка недоступна",
        "Ссылка неверна или владелец её отключил.",
      ],
    },
    statuses: {
      401: ["Сессия завершена", "Войдите снова, чтобы продолжить."],
      403: ["Нет доступа", "У вас нет разрешения на это действие."],
      404: ["Не найдено", "Запрошенный объект не существует."],
      409: ["Состояние изменилось", "Обновите страницу и повторите попытку."],
      413: [
        "Файл слишком большой",
        "Размер каждого файла не должен превышать 20 МБ.",
      ],
      422: ["Запрос не принят", "Проверьте данные и отправьте их снова."],
      429: ["Лимит исчерпан", "Подождите немного, пока лимит обновится."],
      500: ["Ошибка сервиса", "Проблема на нашей стороне. Повторите попытку."],
      502: ["Сервис не отвечает", "Повторите попытку через несколько минут."],
      503: [
        "Сервис временно недоступен",
        "Повторите попытку через несколько минут.",
      ],
    },
    offline: ["Нет подключения", "Проверьте интернет. Данные не получены."],
    generic: [
      "Что-то пошло не так",
      "Повторите попытку. Если ошибка повторится, сообщите нам.",
    ],
    timeout: [
      "Запрос занял слишком много времени",
      "Ответ не пришёл. Повторите попытку.",
    ],
    jobFailed: "Генерация остановлена",
    jobIncomplete: "Процесс не завершился.",
    jobNoReason: "Процесс не завершился, причина не записана.",
    stoppedAt: (step: string) => `Остановка на этапе «${step}».`,
    balance: (balance: string, required: string, missing: string) =>
      `На балансе ${balance}. Для этого пакета нужно ${required}; не хватает ${missing}.`,
    resetIn: "Лимит обновится",
    dailyLimit: "Дневной лимит",
    sharedNetwork:
      "Этот лимит действует для всех пользователей одной сети, например одного Wi-Fi.",
  },
} as const;

function localizedAction(action: ErrorAction | undefined, locale: Locale) {
  if (!action || locale === "uz") return action;
  return { ...action, label: ERROR_COPY[locale].actions[action.kind] };
}

function localizedEntry(
  base: Entry | undefined,
  pair: readonly [string, string] | undefined,
  locale: Locale,
): Entry | undefined {
  if (!base) return undefined;
  if (locale === "uz") return base;
  if (!pair) return undefined;
  return {
    ...base,
    title: pair[0],
    message: pair[1],
    action: localizedAction(base.action, locale),
  };
}

function genericEntry(locale: Locale): Entry {
  if (locale === "uz") return GENERIC;
  const copy = ERROR_COPY[locale];
  return {
    title: copy.generic[0],
    message: copy.generic[1],
    action: { label: copy.actions.retry, kind: "retry" },
  };
}

/**
 * The API answers some failures with a JSON object in `detail`, which the
 * client stringifies. Pull the reason back out without letting a parse failure
 * become the user's problem.
 */
function structuredReason(raw: string): {
  reason: string | null;
  fields: Record<string, unknown>;
} {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null)
      return { reason: null, fields: {} };
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
export function describeError(
  error: unknown,
  locale: Locale = "uz",
): FriendlyError {
  if (error instanceof ApiError) {
    const reason = reasonOf(error);
    const localizedReason =
      locale === "uz" || !reason
        ? undefined
        : ERROR_COPY[locale].reasons[
            reason as keyof (typeof ERROR_COPY)[typeof locale]["reasons"]
          ];
    const localizedStatus =
      locale === "uz"
        ? undefined
        : ERROR_COPY[locale].statuses[
            error.status as keyof (typeof ERROR_COPY)[typeof locale]["statuses"]
          ];
    const entry =
      localizedEntry(
        reason ? CATALOG[reason] : undefined,
        localizedReason,
        locale,
      ) ||
      localizedEntry(BY_STATUS[error.status], localizedStatus, locale) ||
      genericEntry(locale);
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
    const entry =
      locale === "uz"
        ? OFFLINE
        : {
            title: ERROR_COPY[locale].offline[0],
            message: ERROR_COPY[locale].offline[1],
            action: {
              label: ERROR_COPY[locale].actions.retry,
              kind: "retry" as const,
            },
          };
    return {
      ...entry,
      tone: "error",
      detail: String(error),
      reason: "network",
    };
  }

  if (error instanceof DOMException && error.name === "AbortError") {
    const timeout = locale === "uz" ? null : ERROR_COPY[locale].timeout;
    return {
      title: timeout?.[0] ?? "So‘rov juda uzoq davom etdi",
      message: timeout?.[1] ?? "Javob kelmadi. Qayta urinib ko‘ring.",
      tone: "error",
      action: localizedAction(RETRY, locale),
      detail: String(error),
      reason: "timeout",
    };
  }

  return {
    ...genericEntry(locale),
    tone: "error",
    detail: String(error),
    reason: null,
  };
}

/**
 * The 402 body carries the real numbers; a fixed sentence that omits them is
 * what made the money moment a dead end (G8). Falls back to the catalog copy
 * when the body is not the shape we expect.
 */
export function creditCopy(
  error: unknown,
  formatSum: (n: number) => string,
  locale: Locale = "uz",
): FriendlyError {
  const base = describeError(error, locale);
  const fields = fieldsOf(error);
  const balance = fields.balance;
  const required = fields.required;
  if (typeof balance !== "number" || typeof required !== "number") return base;
  const formattedBalance = formatSum(balance);
  const formattedRequired = formatSum(required);
  const formattedMissing = formatSum(Math.max(0, required - balance));
  return {
    ...base,
    message:
      locale === "uz"
        ? `Hisobingizda ${formattedBalance}, bu paket uchun ${formattedRequired} kerak. Yetishmayapti: ${formattedMissing}.`
        : ERROR_COPY[locale].balance(
            formattedBalance,
            formattedRequired,
            formattedMissing,
          ),
  };
}

/**
 * 429 copy that states WHEN, instead of asserting "ertaga" for a cap that may
 * reset in twenty minutes, and names the per-IP case so a campus network does
 * not read as the user's own fault (G32).
 */
export function rateLimitCopy(
  error: unknown,
  locale: Locale = "uz",
): FriendlyError {
  const base = describeError(error, locale);
  const fields = fieldsOf(error);
  const resetsAt =
    typeof fields.resets_at === "string" ? new Date(fields.resets_at) : null;
  const scope = fields.scope === "ip" ? "ip" : "user";
  const limit = typeof fields.limit === "number" ? fields.limit : null;

  const when =
    resetsAt && Number.isFinite(resetsAt.getTime())
      ? locale === "uz"
        ? ` Limit ${formatReset(resetsAt, locale)} yangilanadi.`
        : ` ${ERROR_COPY[locale].resetIn} ${formatReset(resetsAt, locale)}.`
      : "";
  const who =
    scope === "ip"
      ? locale === "uz"
        ? " Bu cheklov shu tarmoqdagi barcha foydalanuvchilarga tegishli (masalan, bitta Wi-Fi)."
        : ` ${ERROR_COPY[locale].sharedNetwork}`
      : "";
  const howMany =
    limit !== null
      ? locale === "uz"
        ? ` Kunlik chek: ${limit} ta.`
        : ` ${ERROR_COPY[locale].dailyLimit}: ${limit}.`
      : "";

  return { ...base, message: `${base.message}${howMany}${when}${who}`.trim() };
}

function formatReset(at: Date, locale: Locale = "uz"): string {
  const minutes = Math.round((at.getTime() - Date.now()) / 60_000);
  if (minutes <= 1) {
    return locale === "en"
      ? "in one minute"
      : locale === "ru"
        ? "через минуту"
        : "bir daqiqada";
  }
  if (minutes < 60) {
    return locale === "en"
      ? `in ${minutes} minutes`
      : locale === "ru"
        ? `через ${minutes} мин.`
        : `${minutes} daqiqada`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    return locale === "en"
      ? `in ${hours} hours`
      : locale === "ru"
        ? `через ${hours} ч.`
        : `${hours} soatda`;
  }
  const localeCode =
    locale === "en" ? "en-US" : locale === "ru" ? "ru-RU" : "uz-UZ";
  return at.toLocaleDateString(localeCode, { day: "numeric", month: "long" });
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
export function describeJobFailure(
  errorMessage: string | null,
  locale: Locale = "uz",
): FriendlyError {
  const copy = locale === "uz" ? null : ERROR_COPY[locale];
  const base: FriendlyError = {
    title: copy?.jobFailed ?? "Generatsiya to‘xtadi",
    message: copy?.jobIncomplete ?? "Jarayon tugamadi.",
    tone: "error",
    detail: errorMessage ?? undefined,
    reason: "job_failed",
  };
  if (!errorMessage) {
    return {
      ...base,
      message: copy?.jobNoReason ?? "Jarayon tugamadi. Sababi qayd etilmagan.",
    };
  }

  const separator = errorMessage.indexOf(":");
  const stepKey =
    separator === -1
      ? errorMessage.trim()
      : errorMessage.slice(0, separator).trim();
  const known = stepLabels(locale).find((entry) => entry.key === stepKey);
  if (known) {
    return {
      ...base,
      message:
        copy?.stoppedAt(known.label) ?? `«${known.label}» bosqichida to‘xtadi.`,
    };
  }
  // An unrecognised step name is still not an excuse to print the exception.
  return base;
}
