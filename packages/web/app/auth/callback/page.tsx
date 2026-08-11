"use client";

// Magic-link landing: the Supabase session proves the email; exchange it for
// the app session (the Supabase session is NOT the app credential — plan §5).

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { emailExchange, ApiError } from "@/lib/api";
import { createAnonClient } from "@/lib/supabase";

export default function AuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Require auth evidence in the URL itself (panel finding): getSession()
    // happily returns a PREVIOUSLY stored GoTrue session, so opening an
    // expired/blank callback would exchange the wrong identity instead of
    // failing. Magic links land with ?code= (PKCE) or token_hash/access_token.
    const query = new URLSearchParams(window.location.search);
    const hash = window.location.hash;
    const hasAuthEvidence =
      query.has("code") || query.has("token_hash") || hash.includes("access_token");
    if (!hasAuthEvidence) {
      setError("havola yaroqsiz yoki eskirgan — qaytadan yuboring");
      return;
    }
    const supabase = createAnonClient();
    supabase.auth
      .getSession()
      .then(async ({ data, error: sessionError }) => {
        if (sessionError || !data.session) {
          setError("supabase sessiya topilmadi");
          return;
        }
        await emailExchange(data.session.access_token);
        // Local scope (panel finding, 3 lenses): the default global sign-out
        // revokes the user's Supabase sessions on OTHER devices; this flow only
        // needs to discard the transient magic-link proof session. Best-effort:
        // the app session is already saved, so a failed cleanup is logged, not
        // fatal — the stray GoTrue session is not the app credential.
        const { error: signOutError } = await supabase.auth.signOut({ scope: "local" });
        if (signOutError) {
          console.warn("supabase local sign-out failed after exchange", signOutError.message);
        }
        router.replace("/projects");
      })
      .catch((exchangeError: unknown) => {
        setError(exchangeError instanceof ApiError ? exchangeError.reason : "kutilmagan xato");
      });
  }, [router]);

  return (
    <div className="shell">
      <div className="auth-wrap">
        <div className="auth-card">
          {error ? (
            <div className="state state-error" style={{ padding: "var(--sp-4) 0" }}>
              <div className="state-icon" aria-hidden>
                ⚠️
              </div>
              <h3>Kirish amalga oshmadi</h3>
              <p>{error}</p>
              <a className="btn btn-ghost" href="/login">
                Qaytadan kirish
              </a>
            </div>
          ) : (
            <div className="state" style={{ padding: "var(--sp-4) 0" }}>
              <div className="skeleton" style={{ height: "1.4rem", width: "60%", margin: "0 auto var(--sp-4)" }} />
              <p>Kirilmoqda…</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
