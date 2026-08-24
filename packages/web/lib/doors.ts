// Door logic that has no DOM in it, so the decisions can be tested directly:
// which door a visitor belongs at, whether a magic link may be re-sent yet, and
// how any door failure becomes copy a person can read.
//
// The doors used to fail three ways at once (G28): the "sent" state was
// terminal, Telegram printed its machine reason (`telegram_auth_backend_down`)
// at the user, and the callback leaked "supabase sessiya topilmadi". Everything
// user-facing now leaves this module as a FriendlyError.

import { ApiError } from "./api";
import { describeError, type ErrorAction, type FriendlyError } from "./errors";
import { DEFAULT_RETURN_TO, sanitizeReturnTo } from "./return-to";

const RETRY: ErrorAction = { label: "Qayta urinish", kind: "retry" };
const LOGIN: ErrorAction = { label: "Qaytadan kirish", kind: "login" };

/** A second link cannot be asked for before this passes. */
export const RESEND_COOLDOWN_MS = 60_000;

/**
 * How long the callback waits before it calls the exchange dead. Wider than the
 * 20s AbortSignal in lib/api.ts, so a hung fetch normally reports itself first
 * and this only catches a hang that never became a request at all.
 */
export const CALLBACK_DEADLINE_MS = 25_000;

/** How long the login page waits for telegram.org before deciding without it. */
export const BRIDGE_DEADLINE_MS = 3_000;

export interface ResendState {
  canResend: boolean;
  secondsLeft: number;
}

export function resendState(sentAt: number | null, now: number): ResendState {
  if (sentAt === null) return { canResend: true, secondsLeft: 0 };
  const remaining = sentAt + RESEND_COOLDOWN_MS - now;
  if (remaining <= 0) return { canResend: true, secondsLeft: 0 };
  return { canResend: false, secondsLeft: Math.ceil(remaining / 1000) };
}

export type DoorRoute =
  /** Prove the Telegram identity and mint a session. */
  | "telegram"
  /** Signed in AND inside Telegram: offer to merge the two identities (G26). */
  | "link"
  /** Already through a door — send them where they were going. */
  | "forward"
  /** Show the sign-in choices. */
  | "offer";

export function decideDoor(initData: string | null, hasSession: boolean): DoorRoute {
  if (initData) return hasSession ? "link" : "telegram";
  return hasSession ? "forward" : "offer";
}

/**
 * Whether this URL was opened by the Telegram client.
 *
 * The Mini App hands initData to the page in the fragment; telegram-web-app.js
 * reads it from there. Checking the fragment ourselves is what lets an
 * already-signed-in visitor be forwarded WITHOUT waiting on a third-party
 * script that may be slow, blocked, or absent (G28f) — while still pausing for
 * the bridge when we can see we really are inside Telegram.
 */
export function hasMiniAppMarker(hash: string): boolean {
  return hash.includes("tgWebAppData");
}

/** `/login` carrying the place the user was trying to reach. */
export function loginHref(returnTo: string): string {
  const safe = sanitizeReturnTo(returnTo);
  if (safe === DEFAULT_RETURN_TO) return "/login";
  return `/login?returnTo=${encodeURIComponent(safe)}`;
}

export type LocalDoorFailure =
  | "no_auth_evidence"
  | "no_supabase_session"
  | "timeout"
  | "cancelled"
  | "otp_send_failed"
  | "oauth_start_failed";

const LOCAL: Record<LocalDoorFailure, { title: string; message: string; action?: ErrorAction }> = {
  no_auth_evidence: {
    title: "Havola ishlamadi",
    message: "Havola eskirgan yoki to‘liq ochilmagan. Yangi havola so‘rang.",
    action: LOGIN,
  },
  no_supabase_session: {
    title: "Havola tasdiqlanmadi",
    message: "Bu havola bo‘yicha kirishni tasdiqlab bo‘lmadi. Yangi havola so‘rang.",
    action: LOGIN,
  },
  timeout: {
    title: "Kirish juda uzoq davom etdi",
    message: "Javob kelmadi. Ulanishni tekshirib, qaytadan kiring.",
    action: LOGIN,
  },
  cancelled: {
    title: "Kirish bekor qilindi",
    message: "Xohlagan paytda qaytadan kirishingiz mumkin.",
    action: LOGIN,
  },
  otp_send_failed: {
    title: "Havola yuborilmadi",
    message: "Email manzilni tekshirib, qayta urinib ko‘ring.",
    action: RETRY,
  },
  oauth_start_failed: {
    title: "Google bilan kirib bo‘lmadi",
    message: "Google sahifasi ochilmadi. Qayta urinib ko‘ring yoki email orqali kiring.",
    action: RETRY,
  },
};

/** Copy for a failure we detected ourselves, with no server reason to map. */
export function localDoorFailure(kind: LocalDoorFailure, detail?: string): FriendlyError {
  const entry = LOCAL[kind];
  return {
    title: entry.title,
    message: entry.message,
    tone: "error",
    action: entry.action,
    detail,
    reason: kind,
  };
}

interface SupabaseAuthErrorish {
  name: string;
  message: string;
}

function isSupabaseAuthError(error: unknown): error is SupabaseAuthErrorish {
  if (!(error instanceof Error)) return false;
  return error.name.startsWith("Auth");
}

/**
 * Any door failure as human copy.
 *
 * ApiError goes through the shared catalog — it already knows
 * `telegram_auth_backend_down` and `initdata_expired`. A GoTrue AuthError is
 * not an ApiError and its `.message` is English SDK prose, so it is named for
 * what it is and its text moves into the collapsible detail.
 */
export function describeDoorFailure(error: unknown, fallback?: LocalDoorFailure): FriendlyError {
  if (error instanceof ApiError) return describeError(error);
  if (isSupabaseAuthError(error)) {
    return localDoorFailure(fallback ?? "otp_send_failed", `${error.name}: ${error.message}`);
  }
  if (fallback && !(error instanceof TypeError)) {
    return localDoorFailure(fallback, String(error));
  }
  return describeError(error);
}
