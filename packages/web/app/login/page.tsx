"use client";

// Identity doors (plan §5 + P3.5 4a). Inside Telegram the Mini App initData
// logs in automatically. In a plain browser Google OAuth is the primary door
// and the email magic link is the fallback; both produce a GoTrue session the
// API exchanges for the SAME app session, so the identity model is identical.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Script from "next/script";
import { GoogleIcon } from "@/components/ui";
import { telegramLogin, ApiError } from "@/lib/api";
import { DEFAULT_RETURN_TO, sanitizeReturnTo, stashReturnTo } from "@/lib/return-to";
import { loadSession } from "@/lib/session";
import { createAnonClient } from "@/lib/supabase";
import { readInitData } from "@/lib/telegram";

type Status =
  | { kind: "idle" }
  | { kind: "working"; message: string }
  | { kind: "sent" }
  | { kind: "error"; message: string };

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  // The Telegram bridge (panel finding): window.Telegram.WebApp only exists
  // once telegram.org/js/telegram-web-app.js loads — without it the Telegram
  // door silently never fires and every in-Telegram user falls through to
  // email. The script loads here, not in the root layout, so the landing does
  // not pay its main-thread cost; onReady fires both on fresh load and when
  // the script is already present after a client-side navigation, so the door
  // check below never races the script.
  const [bridgeReady, setBridgeReady] = useState(false);
  const [returnTo] = useState(() =>
    typeof window === "undefined"
      ? DEFAULT_RETURN_TO
      : sanitizeReturnTo(new URLSearchParams(window.location.search).get("returnTo")),
  );

  useEffect(() => {
    if (!bridgeReady) return;
    const initData = readInitData();
    if (!initData) {
      // A bot link opened in an external browser has no initData but may still
      // carry a live app session; sending it onward beats stranding the user at
      // a door they are already through. Nested here so it can never race the
      // Telegram door — with initData present this branch is unreachable.
      if (loadSession()) router.replace(returnTo);
      return;
    }
    setStatus({ kind: "working", message: "Telegram orqali kirilmoqda…" });
    telegramLogin(initData)
      .then(() => router.replace(returnTo))
      .catch((error: unknown) => {
        const message = error instanceof ApiError ? error.reason : "kutilmagan xato";
        setStatus({ kind: "error", message });
      });
  }, [bridgeReady, returnTo, router]);

  async function signInWithGoogle() {
    stashReturnTo(returnTo);
    setStatus({ kind: "working", message: "Google sahifasiga o'tilmoqda…" });
    try {
      const supabase = createAnonClient();
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: `${window.location.origin}/auth/callback` },
      });
      if (error) throw error;
      // The browser navigates away to Google here; no further state needed.
    } catch {
      setStatus({ kind: "error", message: "Google orqali kirishda xato — qayta urinib ko'ring" });
    }
  }

  async function sendMagicLink() {
    stashReturnTo(returnTo);
    setStatus({ kind: "working", message: "Havola yuborilmoqda…" });
    try {
      const supabase = createAnonClient();
      const { error } = await supabase.auth.signInWithOtp({
        email,
        options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
      });
      if (error) throw error;
      setStatus({ kind: "sent" });
    } catch {
      setStatus({ kind: "error", message: "havola yuborilmadi — emailni tekshiring" });
    }
  }

  const working = status.kind === "working";

  return (
    <div className="dark auth-min">
      <Script
        src="https://telegram.org/js/telegram-web-app.js"
        onReady={() => setBridgeReady(true)}
      />
      <Link href="/" className="auth-min-brand">
        Nashr
      </Link>

      <div className="auth-min-form">
        <div className="page-head">
          <h1 className="page-title">Kirish</h1>
          <p className="page-sub">Loyihalaringiz va taqdimotlaringizga qaytish.</p>
        </div>

        <div className="card">
          {status.kind === "error" && (
            <p style={{ color: "var(--danger)", fontSize: "var(--text-sm)", fontWeight: 600 }}>
              {status.message}
            </p>
          )}
          {working && <p style={{ color: "var(--muted-ink)" }}>{status.message}</p>}

          {status.kind === "sent" ? (
            <div className="state" style={{ padding: "var(--sp-5) 0" }}>
              <h3>Email yuborildi</h3>
              <p>Pochtangizni oching va xatdagi havolani bosing — shu yerga qaytasiz.</p>
            </div>
          ) : (
            <>
              <button
                className="btn btn-ghost btn-lg btn-block"
                onClick={() => void signInWithGoogle()}
                disabled={working}
              >
                <GoogleIcon />
                Google bilan kirish
              </button>

              <div className="divider">yoki email orqali</div>

              <label
                htmlFor="email"
                style={{
                  display: "block",
                  color: "var(--muted-ink)",
                  fontSize: "var(--text-sm)",
                  marginBottom: "var(--sp-2)",
                }}
              >
                Email manzil
              </label>
              <input
                className="input"
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                value={email}
                placeholder="email@example.com"
                onChange={(event) => setEmail(event.target.value)}
                style={{ marginBottom: "var(--sp-3)" }}
              />
              <button
                className="btn btn-primary btn-block"
                onClick={() => void sendMagicLink()}
                disabled={!email || working}
              >
                Havola yuborish
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
