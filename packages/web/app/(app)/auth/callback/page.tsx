"use client";

// Magic-link landing: the Supabase session proves the email; exchange it for
// the app session (the Supabase session is NOT the app credential — plan §5).
//
// Three G28 defects lived here. "Kirilmoqda…" had no deadline, so a hung
// exchange spun forever with no way out. Failures leaked internal vocabulary
// straight at the user — "supabase sessiya topilmadi", "exchange failed:
// upstream 500" — which names our own plumbing at someone who just clicked a
// link in their mail. And "Qaytadan kirish" dropped returnTo, so a user who
// was mid-flow when their session lapsed landed on an empty folio instead of
// where they were going.

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { emailExchange } from "@/lib/api";
import type { FriendlyError } from "@/lib/errors";
import { CALLBACK_DEADLINE_MS, describeDoorFailure, localDoorFailure, loginHref } from "@/lib/doors";
import { consumeReturnTo, DEFAULT_RETURN_TO, stashReturnTo } from "@/lib/return-to";
import { createAnonClient } from "@/lib/supabase";
import "../../doors.css";

export default function AuthCallbackPage() {
  const router = useRouter();
  const [failure, setFailure] = useState<FriendlyError | null>(null);
  // Where the user was going. Read (and cleared) on the success path; captured
  // up front so a FAILURE can carry it into the login link rather than losing
  // it, which is what stranded people on /projects.
  const intended = useRef<string>(DEFAULT_RETURN_TO);
  const settled = useRef(false);

  const finish = useCallback((error: FriendlyError | null) => {
    if (settled.current) return;
    settled.current = true;
    setFailure(error);
  }, []);

  useEffect(() => {
    // Require auth evidence in the URL itself: getSession() happily returns a
    // PREVIOUSLY stored GoTrue session, so opening a blank callback would
    // exchange the wrong identity instead of failing. Magic links land with
    // ?code= (PKCE) or token_hash/access_token.
    const query = new URLSearchParams(window.location.search);
    const hash = window.location.hash;
    const hasAuthEvidence =
      query.has("code") || query.has("token_hash") || hash.includes("access_token");
    if (!hasAuthEvidence) {
      finish(localDoorFailure("no_auth_evidence"));
      return;
    }

    // A deadline, so a hung exchange becomes a state the user can act on
    // instead of a spinner with no end.
    const deadline = window.setTimeout(
      () => finish(localDoorFailure("timeout")),
      CALLBACK_DEADLINE_MS,
    );

    const supabase = createAnonClient();
    supabase.auth
      .getSession()
      .then(async ({ data, error: sessionError }) => {
        if (sessionError || !data.session) {
          finish(localDoorFailure("no_supabase_session", sessionError?.message));
          return;
        }
        await emailExchange(data.session.access_token);
        // Local scope: the default global sign-out revokes the user's Supabase
        // sessions on OTHER devices; this flow only needs to discard the
        // transient magic-link proof session. Best-effort — the app session is
        // already saved, so a failed cleanup is logged, not fatal.
        const { error: signOutError } = await supabase.auth.signOut({ scope: "local" });
        if (signOutError) {
          console.warn("supabase local sign-out failed after exchange", signOutError.message);
        }
        if (settled.current) return;
        settled.current = true;
        const destination = consumeReturnTo();
        intended.current = destination;
        router.replace(destination);
      })
      .catch((exchangeError: unknown) => {
        finish(describeDoorFailure(exchangeError, "no_supabase_session"));
      });

    return () => window.clearTimeout(deadline);
  }, [router, finish]);

  // A failed exchange must not eat the destination: re-stash it so the door the
  // user is sent back to still knows where they were going (G28e).
  function retryHref(): string {
    const destination = consumeReturnTo();
    if (destination !== DEFAULT_RETURN_TO) stashReturnTo(destination);
    return loginHref(destination);
  }

  return (
    <div className="auth-shell">
      <Link href="/" className="auth-brand">
        Nashr
      </Link>

      <div className="auth-body">
        <div className="auth-card">
          {failure !== null ? (
            <div className="auth-fail" role="alert">
              <p className="auth-fail-title">{failure.title}</p>
              <p className="auth-fail-message">{failure.message}</p>
              {failure.detail !== undefined && (
                <details className="auth-detail">
                  <summary>Texnik tafsilot</summary>
                  <code>{failure.detail}</code>
                </details>
              )}
              <a className="btn btn-ghost" href={retryHref()}>
                <span className="btn-label">{failure.action?.label ?? "Qaytadan kirish"}</span>
              </a>
            </div>
          ) : (
            <div className="state state-blank">
              <div
                className="skeleton"
                style={{ height: "1.4rem", width: "60%", margin: "0 auto 16px" }}
              />
              <p>Kirilmoqda…</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
