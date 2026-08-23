"use client";

// The session, as every authed page consumes it.
//
// Three defects in the audit share one root cause — the session was checked
// once, at mount, and never again (G6, G15, and half of G12):
//
//   * a token that died mid-job took the whole run down with it: one 401
//     stopped polling, showed a 4-second raw toast, and left the paid start
//     button on screen while the job kept running server-side;
//   * nothing ever renewed the 1h token;
//   * a 401 never sent anyone back to a door, let alone back to where they were.
//
// So the session refreshes PROACTIVELY here. `POST /auth/refresh` re-mints from
// a token that is still valid, which means it cannot rescue an expired one — a
// refresh triggered BY a 401 has already lost. The timer is the mechanism; the
// 401 path is the safety net that sends the user to a door carrying returnTo.

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, refreshSession } from "./api";
import { type AppSession, clearSession, loadSession } from "./session";

/** Renew this long before expiry. Comfortably wider than any single request. */
const REFRESH_LEAD_MS = 5 * 60 * 1000;
/** Never schedule a tighter loop than this, whatever the clock says. */
const MIN_REFRESH_DELAY_MS = 15 * 1000;

export function msUntilRefresh(session: AppSession, now = Date.now()): number {
  const expiry = new Date(session.expiresAt).getTime();
  if (!Number.isFinite(expiry)) return MIN_REFRESH_DELAY_MS;
  return Math.max(MIN_REFRESH_DELAY_MS, expiry - now - REFRESH_LEAD_MS);
}

export interface UseSession {
  session: AppSession | null;
  /** True until the first load settles, so pages can hold their skeleton. */
  loading: boolean;
  /** Send the user to a door, remembering where they were. */
  toLogin: () => void;
  /**
   * Run an authed call, refreshing once on 401 before giving up. Returns null
   * when the session is genuinely gone (the caller has already been redirected).
   */
  withAuth: <T>(call: (token: string) => Promise<T>) => Promise<T | null>;
}

export function useAppSession(): UseSession {
  const router = useRouter();
  const [session, setSession] = useState<AppSession | null>(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef<number | null>(null);
  // Read by withAuth without re-creating the callback on every renewal, which
  // would restart every effect that depends on it (and thus every poll).
  const current = useRef<AppSession | null>(null);

  const toLogin = useCallback(() => {
    const here = window.location.pathname + window.location.search;
    clearSession();
    current.current = null;
    setSession(null);
    router.replace(`/login?returnTo=${encodeURIComponent(here)}`);
  }, [router]);

  const adopt = useCallback((next: AppSession) => {
    current.current = next;
    setSession(next);
  }, []);

  const scheduleRefresh = useCallback(
    (active: AppSession) => {
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        const held = current.current;
        if (!held) return;
        refreshSession(held.accessToken)
          .then((next) => {
            adopt(next);
            scheduleRefresh(next);
          })
          .catch(() => {
            // The renewal failed while the token was still valid — a transient
            // network blip, most likely. Try again shortly rather than logging
            // the user out of a session that has not actually expired.
            timer.current = window.setTimeout(() => scheduleRefresh(held), MIN_REFRESH_DELAY_MS);
          });
      }, msUntilRefresh(active));
    },
    [adopt],
  );

  useEffect(() => {
    const active = loadSession();
    setLoading(false);
    if (!active) {
      toLogin();
      return;
    }
    adopt(active);
    scheduleRefresh(active);
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, [adopt, scheduleRefresh, toLogin]);

  const withAuth = useCallback(
    async <T,>(call: (token: string) => Promise<T>): Promise<T | null> => {
      const held = current.current;
      if (!held) return null;
      try {
        return await call(held.accessToken);
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error;
        // Long shot by construction — refresh needs a live token — but a clock
        // skew or a token rotated in another tab is recoverable, and trying
        // costs one request against certainly losing the user's place.
        try {
          const next = await refreshSession(held.accessToken);
          adopt(next);
          scheduleRefresh(next);
          return await call(next.accessToken);
        } catch {
          toLogin();
          return null;
        }
      }
    },
    [adopt, scheduleRefresh, toLogin],
  );

  return { session, loading, toLogin, withAuth };
}
