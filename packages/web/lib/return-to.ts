// Where a door sends the user after login. Two carriers: the ?returnTo URL param
// (same-tab navigations) and a localStorage stash for the OAuth/magic-link doors,
// which round-trip through Google or a mail client and lose the param. We do NOT
// append query params to the Supabase redirectTo: the GoTrue redirect allow-list
// on prod may reject the decorated URL and silently fall back to SITE_URL, which
// breaks login outright. localStorage is shared across tabs, so a magic link
// opened in a fresh tab still lands on the right page.

export const DEFAULT_RETURN_TO = "/projects";

const STORAGE_KEY = "nashr.returnTo";
const TTL_MS = 60 * 60 * 1000;
const MAX_LENGTH = 512;
const UNSAFE_CHARS = /[\s\u0000-\u001f\u007f]/;

export function sanitizeReturnTo(raw: string | null | undefined): string {
  if (typeof raw !== "string") return DEFAULT_RETURN_TO;
  if (raw.length === 0 || raw.length > MAX_LENGTH) return DEFAULT_RETURN_TO;
  if (raw[0] !== "/") return DEFAULT_RETURN_TO;
  // "//evil.com" is protocol-relative and "/\evil.com" is normalized to it by
  // every browser — both leave the origin.
  if (raw[1] === "/" || raw[1] === "\\") return DEFAULT_RETURN_TO;
  if (UNSAFE_CHARS.test(raw)) return DEFAULT_RETURN_TO;
  const queryStart = raw.indexOf("?");
  const path = queryStart === -1 ? raw : raw.slice(0, queryStart);
  if (path.includes(":")) return DEFAULT_RETURN_TO;
  return raw;
}

export function stashReturnTo(path: string): void {
  if (typeof window === "undefined") return;
  const payload = { path: sanitizeReturnTo(path), exp: Date.now() + TTL_MS };
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

export function consumeReturnTo(): string {
  if (typeof window === "undefined") return DEFAULT_RETURN_TO;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  window.localStorage.removeItem(STORAGE_KEY);
  if (!raw) return DEFAULT_RETURN_TO;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return DEFAULT_RETURN_TO;
    const candidate = parsed as Record<string, unknown>;
    if (typeof candidate.exp !== "number" || candidate.exp <= Date.now()) {
      return DEFAULT_RETURN_TO;
    }
    if (typeof candidate.path !== "string") return DEFAULT_RETURN_TO;
    // Stored value is untrusted (any script on the origin can write it).
    return sanitizeReturnTo(candidate.path);
  } catch {
    return DEFAULT_RETURN_TO;
  }
}
