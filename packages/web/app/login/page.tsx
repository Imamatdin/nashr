"use client";

// Both identity doors (plan §5). Inside Telegram the Mini App initData logs in
// automatically; in a plain browser the email magic link is offered. Either
// door ends in the SAME app session minted by the API.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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

  return (
    <main>
      <h1>Kirish</h1>
      {status.kind === "error" && <p style={{ color: "crimson" }}>Xato: {status.message}</p>}
      {status.kind === "working" && <p>{status.message}</p>}
      {status.kind === "sent" ? (
        <p>Email yuborildi — havolani oching.</p>
      ) : (
        <div>
          <input
            type="email"
            value={email}
            placeholder="email@example.com"
            onChange={(event) => setEmail(event.target.value)}
          />
          <button onClick={sendMagicLink} disabled={!email || status.kind === "working"}>
            Magic link yuborish
          </button>
        </div>
      )}
    </main>
  );
}
