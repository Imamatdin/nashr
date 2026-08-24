// What a share-link recipient is told — the two facts the old viewer got wrong.
//
// 1. Lifetime. `expires_in` on the public payload is the SIGNED-URL TTL (900 s
//    for the HTML, 3600 s for a download), never the link's. The share token
//    itself has no expiry at all: it dies when its owner disables or rotates
//    it. The old caption divided the TTL by 86400 and announced a day count,
//    so production told every visitor "1 KUNDAN KEYIN YOPILADI" about a link
//    that closes when the owner says so (G19/G20). No day count is derivable
//    from this number; the only honest report is minutes, next to the files
//    the URL actually signs.
//
// 2. Failure. 404 (no such link / disabled), 410 (rotated away) and 500 are
//    three different situations with three different next moves, and retry
//    helps for exactly one of them. `describeError` covers 404/500/timeout/
//    offline; 410 has no catalog entry and would fall through to the generic
//    "qayta urinib ko‘ring", which on a dead token is a lie — so it is
//    classified here before delegating.

import { ApiError } from "./api";
import { describeError, rateLimitCopy } from "./errors";

export interface ShareFailure {
  title: string;
  message: string;
  /** Machine string for the collapsible detail. Never rendered inline. */
  detail?: string;
  /** True only when trying again can plausibly produce a different answer. */
  retryable: boolean;
  /** Matched reason code, or null when we fell through. */
  reason: string | null;
}

export function classifyShareFailure(error: unknown): ShareFailure {
  if (error instanceof ApiError && error.status === 410) {
    return {
      title: "Havola yangilangan",
      message:
        "Bu havola endi ishlamaydi — egasi uni yangilagan. Undan yangi havolani so‘rang.",
      detail: `HTTP ${error.status} · ${error.reason}`,
      retryable: false,
      reason: "share_rotated",
    };
  }

  if (error instanceof ApiError && error.status === 429) {
    const limited = rateLimitCopy(error);
    return {
      title: limited.title,
      message: limited.message,
      detail: limited.detail,
      retryable: true,
      reason: limited.reason,
    };
  }

  const described = describeError(error);
  const isMissing =
    described.reason === "not_found" ||
    (error instanceof ApiError && error.status === 404);

  return {
    title: isMissing ? "Havola ishlamaydi" : described.title,
    message: isMissing
      ? "Bu havola noto‘g‘ri yoki egasi uni o‘chirgan. Taqdimot egasidan yangi havola so‘rang."
      : described.message,
    detail: described.detail,
    // A retry button on a 404 is a lie: the token will be just as absent on the
    // second press.
    retryable: !isMissing && described.action?.kind === "retry",
    reason: described.reason,
  };
}

/** "15 daqiqa" / "1 soat" for a signed-URL TTL. Never a day count. */
export function signedUrlLifetime(expiresIn: number): string | null {
  if (!Number.isFinite(expiresIn) || expiresIn <= 0) return null;
  const minutes = Math.round(expiresIn / 60);
  if (minutes < 1) return "bir daqiqadan kam";
  if (minutes < 60) return `${minutes} daqiqa`;
  const hours = Math.round(minutes / 60);
  return `${hours} soat`;
}

/**
 * The download row's note. The lifetime belongs to the file URLs the page was
 * just handed, so it is read off the download itself — the HTML frame's TTL is
 * a different, shorter number.
 */
export function downloadFreshnessNote(expiresIn: number): string {
  const lifetime = signedUrlLifetime(expiresIn);
  return lifetime === null
    ? "Fayl havolalari qisqa muddat amal qiladi. Ishlamay qolsa, sahifani yangilang."
    : `Fayl havolalari taxminan ${lifetime} amal qiladi. Muddati o‘tsa, sahifani yangilang.`;
}

/** What the caption says about the link's own lifetime. Constant by design. */
export const LINK_LIFETIME_CAPTION =
  "NASHR BILAN BOSILDI · HAVOLA EGASI O‘CHIRGUNCHA OCHIQ";
