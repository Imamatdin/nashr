"use client";

// Identity doors. Inside Telegram the Mini App initData logs in automatically;
// in a plain browser Google OAuth is the primary door and the email magic link
// is the fallback. Both produce a GoTrue session the API exchanges for the SAME
// app session, so the identity model is identical whichever door is used.
//
// The audit found this surface failing three ways at once (G28): the magic-link
// "sent" state REPLACED the whole form, so a typo'd address meant a reload with
// nothing on screen to correct; the Telegram door printed its machine reason
// (`telegram_auth_backend_down`) at the user; and an already-signed-in visitor
// was forwarded only if a third-party script happened to load. It also had no
// answer at all for G26 — a person who paid inside the bot and then signed in
// with Google holds two accounts, and nothing offered to join them.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Script from "next/script";
import { Button, GoogleIcon } from "@/components/ui";
import { linkTelegram, telegramLogin } from "@/lib/api";
import type { FriendlyError } from "@/lib/errors";
import {
  BRIDGE_DEADLINE_MS,
  decideDoor,
  describeDoorFailure,
  hasMiniAppMarker,
  resendState,
} from "@/lib/doors";
import { DEFAULT_RETURN_TO, sanitizeReturnTo, stashReturnTo } from "@/lib/return-to";
import { loadSession } from "@/lib/session";
import { createAnonClient } from "@/lib/supabase";
import { readInitData } from "@/lib/telegram";
import "../doors.css";

type Status =
  | { kind: "idle" }
  | { kind: "working"; message: string }
  | { kind: "sent" }
  | { kind: "linked"; merged: boolean }
  | { kind: "error"; error: FriendlyError };

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [sentAt, setSentAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  // The bridge is the telegram-web-app.js script. It only ever MATTERS inside
  // the Telegram webview, so waiting on it is gated on the fragment marker: a
  // normal browser must not be held at a door it is already through because a
  // third-party script is slow, blocked, or absent (G28f).
  const [bridgeSettled, setBridgeSettled] = useState(false);
  const [returnTo] = useState(() =>
    typeof window === "undefined"
      ? DEFAULT_RETURN_TO
      : sanitizeReturnTo(new URLSearchParams(window.location.search).get("returnTo")),
  );

  const fail = useCallback((error: unknown, fallback?: Parameters<typeof describeDoorFailure>[1]) => {
    setStatus({ kind: "error", error: describeDoorFailure(error, fallback) });
  }, []);

  // Never wait on the bridge longer than it can plausibly help.
  useEffect(() => {
    if (bridgeSettled) return;
    if (typeof window !== "undefined" && !hasMiniAppMarker(window.location.hash)) {
      setBridgeSettled(true);
      return;
    }
    const timer = window.setTimeout(() => setBridgeSettled(true), BRIDGE_DEADLINE_MS);
    return () => window.clearTimeout(timer);
  }, [bridgeSettled]);

  // Ticks the resend cooldown down. Runs only while a link is actually cooling.
  useEffect(() => {
    if (sentAt === null) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [sentAt]);

  useEffect(() => {
    if (!bridgeSettled) return;
    const initData = readInitData();
    const session = loadSession();
    const door = decideDoor(initData, session !== null);

    if (door === "forward") {
      router.replace(returnTo);
      return;
    }
    if (door === "offer") return;

    if (door === "telegram" && initData) {
      setStatus({ kind: "working", message: "Telegram orqali kirilmoqda…" });
      telegramLogin(initData)
        .then(() => router.replace(returnTo))
        .catch(fail);
      return;
    }
    // door === "link": signed in AND inside Telegram, which is the only place
    // initData exists — so this is the one moment the two identities can be
    // joined (G26). Offered, never automatic: merging accounts is the user's
    // decision, not a side effect of opening a link.
  }, [bridgeSettled, returnTo, router, fail]);

  async function signInWithGoogle() {
    stashReturnTo(returnTo);
    setStatus({ kind: "working", message: "Google sahifasiga o‘tilmoqda…" });
    try {
      const supabase = createAnonClient();
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: `${window.location.origin}/auth/callback` },
      });
      if (error) throw error;
      // The browser navigates away to Google here; no further state needed.
    } catch (error) {
      fail(error, "oauth_start_failed");
    }
  }

  const sendMagicLink = useCallback(
    async (address: string) => {
      stashReturnTo(returnTo);
      setStatus({ kind: "working", message: "Havola yuborilmoqda…" });
      try {
        const supabase = createAnonClient();
        const { error } = await supabase.auth.signInWithOtp({
          email: address,
          options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
        });
        if (error) throw error;
        setSentTo(address);
        setSentAt(Date.now());
        setNow(Date.now());
        setStatus({ kind: "sent" });
      } catch (error) {
        fail(error, "otp_send_failed");
      }
    },
    [returnTo, fail],
  );

  async function joinTelegramAccount() {
    const initData = readInitData();
    if (!initData) return;
    const session = loadSession();
    if (!session) return;
    setStatus({ kind: "working", message: "Hisoblar birlashtirilmoqda…" });
    try {
      const result = await linkTelegram(initData, session.accessToken);
      setStatus({ kind: "linked", merged: result.merged });
    } catch (error) {
      fail(error);
    }
  }

  const working = status.kind === "working";
  const resend = resendState(sentAt, now);
  const canOfferLink = bridgeSettled && readInitData() !== null && loadSession() !== null;

  return (
    <div className="auth-shell">
      <Script src="https://telegram.org/js/telegram-web-app.js" onReady={() => setBridgeSettled(true)} />
      <Link href="/" className="auth-brand">
        Nashr
      </Link>

      <div className="auth-body">
        <div className="auth-head">
          <h1 className="auth-title">Kirish</h1>
          <p className="auth-sub">Loyihalaringiz va taqdimotlaringizga qaytish.</p>
        </div>

        <div className="auth-card">
          {status.kind === "error" && (
            <div className="auth-fail" role="alert">
              <p className="auth-fail-title">{status.error.title}</p>
              <p className="auth-fail-message">{status.error.message}</p>
              {status.error.detail !== undefined && (
                <details className="auth-detail">
                  <summary>Texnik tafsilot</summary>
                  <code>{status.error.detail}</code>
                </details>
              )}
            </div>
          )}
          {working && <p className="auth-status">{status.message}</p>}

          {status.kind === "linked" ? (
            <div className="state state-blank">
              <h3>{status.merged ? "Hisoblar birlashtirildi" : "Telegram ulandi"}</h3>
              <p>
                {status.merged
                  ? "Telegramdagi loyihalaringiz va krediting shu hisobga o‘tdi."
                  : "Bu Telegram hisobi allaqachon shu foydalanuvchiga bog‘langan edi."}
              </p>
              <Button onClick={() => router.replace(returnTo)}>Davom etish</Button>
            </div>
          ) : canOfferLink ? (
            // G26: the ONLY context where this can work — initData exists only
            // inside the Telegram webview, so a normal browser tab never sees
            // this and is never offered something it cannot do.
            <div className="state state-blank">
              <h3>Telegram hisobingizni ulaymizmi?</h3>
              <p>
                Botda to‘lagan kredit va u yerdagi loyihalar shu hisobga qo‘shiladi. Aks holda
                ular alohida hisobda qoladi.
              </p>
              <Button onClick={() => void joinTelegramAccount()} disabled={working}>
                Ulash
              </Button>
              <button type="button" className="auth-quiet" onClick={() => router.replace(returnTo)}>
                Hozir emas
              </button>
            </div>
          ) : status.kind === "sent" ? (
            // The address stays on screen and the form stays reachable: the old
            // terminal state left a user who mistyped their email with nothing
            // to correct and no way back (G28a).
            <div className="auth-sent">
              <h3>Havola yuborildi</h3>
              <p>
                <span className="auth-sent-address">{sentTo}</span> manziliga havola ketdi.
                Pochtangizni oching va havolani bosing — shu yerga qaytasiz.
              </p>
              <div className="auth-sent-actions">
                <Button
                  variant="ghost"
                  disabled={!resend.canResend || working}
                  onClick={() => sentTo !== null && void sendMagicLink(sentTo)}
                >
                  {resend.canResend
                    ? "Qayta yuborish"
                    : `Qayta yuborish (${resend.secondsLeft}s)`}
                </Button>
                <button
                  type="button"
                  className="auth-quiet"
                  onClick={() => {
                    setStatus({ kind: "idle" });
                    setSentAt(null);
                  }}
                >
                  Boshqa manzil
                </button>
              </div>
            </div>
          ) : (
            <>
              <Button
                variant="ghost"
                size="lg"
                block
                onClick={() => void signInWithGoogle()}
                disabled={working}
              >
                <GoogleIcon />
                Google bilan kirish
              </Button>

              <div className="auth-divider">yoki email orqali</div>

              <div className="field">
                <label htmlFor="email" className="field-label">
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
                />
              </div>

              <Button
                block
                onClick={() => void sendMagicLink(email)}
                disabled={!email || working}
              >
                Havola yuborish
              </Button>
            </>
          )}
        </div>

        <p className="auth-foot">
          Kirish orqali manbaga asoslangan nashr qoidalariga rozilik bildirasiz.
        </p>
      </div>
    </div>
  );
}
