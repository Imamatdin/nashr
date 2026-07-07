// App session (the FastAPI-minted Path A JWT) — the ONLY credential this tier
// stores. localStorage is acceptable for v1: the token is short-lived (1h) and
// the API re-issues via the doors; revisit httpOnly cookies with the P4 chat work.

export interface AppSession {
  accessToken: string;
  expiresAt: string;
  userId: string;
}

const STORAGE_KEY = "nashr.session";

export function saveSession(session: AppSession): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

function isAppSession(value: unknown): value is AppSession {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.accessToken === "string" &&
    candidate.accessToken.length > 0 &&
    typeof candidate.userId === "string" &&
    candidate.userId.length > 0 &&
    typeof candidate.expiresAt === "string" &&
    Number.isFinite(new Date(candidate.expiresAt).getTime())
  );
}

export function loadSession(): AppSession | null {
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    // Validated, not cast (panel finding): malformed stored JSON — including a
    // NaN expiresAt, which passes a naive `<=` check — must clear and re-login,
    // never ride into Supabase as `Bearer undefined`.
    const parsed: unknown = JSON.parse(raw);
    if (!isAppSession(parsed) || new Date(parsed.expiresAt).getTime() <= Date.now()) {
      window.localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return parsed;
  } catch {
    window.localStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

export function clearSession(): void {
  window.localStorage.removeItem(STORAGE_KEY);
}
