"use client";

// Identity doors (plan §5 + P3.5 4a). Inside Telegram the Mini App initData
// logs in automatically. In a plain browser Google OAuth is the primary door
// and the email magic link is the fallback; both produce a GoTrue session the
// API exchanges for the SAME app session, so the identity model is identical.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { GoogleIcon } from "@/components/ui";
import { telegramLogin, ApiError } from "@/lib/api";
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

  useEffect(() => {
    const initData = readInitData();
    if (!initData) return;
    setStatus({ kind: "working", message: "Telegram orqali kirilmoqda…" });
    telegramLogin(initData)
      .then(() => router.replace("/projects"))
      .catch((error: unknown) => {
        const message = error instanceof ApiError ? error.reason : "kutilmagan xato";
        setStatus({ kind: "error", message });
      });
  }, [router]);

  async function signInWithGoogle() {
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
    <div className="shell">
      <header className="topbar">
        <div className="container topbar-inner">
          <Link href="/" className="wordmark">
            Nashr
          </Link>
        </div>
      </header>

      <div className="auth-wrap">
        <div className="auth-card">
          <h1 style={{ marginBottom: "0.4rem" }}>Kirish</h1>
          <p style={{ color: "var(--muted)" }}>Loyihalaringiz va taqdimotlaringizga qaytish.</p>

          {status.kind === "error" && (
            <p style={{ color: "var(--danger)", fontSize: "var(--text-sm)", fontWeight: 600 }}>
              {status.message}
            </p>
          )}
          {working && <p style={{ color: "var(--muted)" }}>{status.message}</p>}

          {status.kind === "sent" ? (
            <div className="state" style={{ padding: "var(--sp-5) 0" }}>
              <div className="state-icon" aria-hidden>
                ✉️
              </div>
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

              <input
                className="input"
                type="email"
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
