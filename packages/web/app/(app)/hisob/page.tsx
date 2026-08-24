"use client";

// The money, made visible (audit §2.4).
//
// G8: until now the balance existed in exactly one place — inside the 402 that
// refused a job — so nobody could see what they had, what a run had cost, or
// that the worker had refunded them. G24: every web source upload grants a
// free credit and the user was told nothing at all.
//
// Read-only by construction. There is no web payment route this run (the
// merchant question is open), so where a user would top up, this page says
// plainly that payment happens in the Telegram bot and links to it rather than
// inventing a checkout the product does not have.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Wallet } from "lucide-react";
import { AppChrome } from "@/components/chrome";
import { Button, DataText, EmptyState } from "@/components/ui";
import { getLedger, type LedgerView } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { describeLedgerEntry } from "@/lib/ledger";
import { soum } from "@/lib/packages";
import { useAppSession } from "@/lib/use-session";
import "./hisob.css";

const BOT_URL = "https://t.me/nashr_ai_bot";

/** Top-up, stated honestly: there is no web checkout, and this says so. */
function TopUp() {
  return (
    <p className="hisob-topup">
      To‘ldirish hozircha Telegram botda amalga oshiriladi —{" "}
      <a href={BOT_URL} target="_blank" rel="noreferrer">
        botni ochish
      </a>
      .
    </p>
  );
}

/**
 * A failure that looks like a failure (G12).
 *
 * The eternal skeleton is the defect this replaces: an unreachable backend
 * used to be indistinguishable from a slow one. Copy comes from
 * describeError, so the machine string lives only inside the disclosure.
 */
function LedgerError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const friendly = describeError(error);
  return (
    <div className="hisob-error" role="alert">
      <p className="hisob-error-title">{friendly.title}</p>
      <p className="hisob-error-message">{friendly.message}</p>
      <div className="hisob-error-actions">
        <Button variant="ghost" onClick={onRetry}>
          {friendly.action?.kind === "retry" ? friendly.action.label : "Qayta urinish"}
        </Button>
      </div>
      {friendly.detail !== undefined && (
        <details className="hisob-detail">
          <summary>Texnik tafsilot</summary>
          <code>{friendly.detail}</code>
        </details>
      )}
    </div>
  );
}

function LedgerRows({ view }: { view: LedgerView }) {
  return (
    <ul className="hisob-list">
      {view.entries.map((entry) => {
        const row = describeLedgerEntry(entry);
        return (
          <li key={entry.id} className="hisob-row" data-tone={row.tone}>
            <div className="hisob-row-main">
              <p className="hisob-row-label">{row.label}</p>
              {row.note !== null && <p className="hisob-row-note">{row.note}</p>}
              {row.href !== null && (
                <Link href={row.href} className="hisob-row-link">
                  Loyihani ochish
                </Link>
              )}
            </div>
            <p className="hisob-row-amount" data-sign={entry.amount < 0 ? "minus" : "plus"}>
              <DataText>{row.amount}</DataText>
            </p>
            <p className="hisob-row-date">
              <DataText>{row.date}</DataText>
            </p>
          </li>
        );
      })}
    </ul>
  );
}

export default function HisobPage() {
  const { session, withAuth } = useAppSession();
  const [view, setView] = useState<LedgerView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const ready = session !== null;

  const load = useCallback(() => {
    setError(null);
    withAuth((token) => getLedger(token))
      .then((next) => {
        // null means the session is gone and withAuth has already redirected.
        if (next) setView(next);
      })
      .catch((failure: unknown) => setError(failure));
  }, [withAuth]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  const loading = view === null && error === null;
  const blank = view !== null && view.entries.length === 0;

  return (
    <AppChrome active="hisob">
      <div className="hisob">
        <header className="hisob-head">
          <p className="hisob-eyebrow">
            <Wallet size={15} strokeWidth={1.75} aria-hidden />
            Hisob
          </p>
          {loading ? (
            <div className="skeleton hisob-balance-skeleton" aria-label="Yuklanmoqda" />
          ) : view !== null ? (
            <p className="hisob-balance">
              <DataText>{soum(view.balance)}</DataText>
            </p>
          ) : null}
          <p className="hisob-sub">
            Taqdimot yaratilganda narx shu hisobdan yechiladi. Generatsiya muvaffaqiyatsiz tugasa,
            mablag‘ avtomatik qaytariladi.
          </p>
          <TopUp />
        </header>

        <h2 className="hisob-section">Harakatlar tarixi</h2>

        {error !== null && <LedgerError error={error} onRetry={load} />}

        {loading && (
          <ul className="hisob-list" aria-busy="true" aria-label="Tarix yuklanmoqda">
            {[0, 1, 2, 3].map((index) => (
              <li key={index} className="hisob-row hisob-row-ghost">
                <div className="hisob-row-main">
                  <div className="skeleton hisob-ghost-label" />
                  <div className="skeleton hisob-ghost-note" />
                </div>
                <div className="skeleton hisob-ghost-amount" />
              </li>
            ))}
          </ul>
        )}

        {blank && (
          <EmptyState
            title="Hozircha harakat yo‘q"
            hint="Birinchi taqdimotingizni yaratganingizda yoki manba yuklaganingizda shu yerda yozuv paydo bo‘ladi."
          >
            <Link href="/new" className="btn btn-primary">
              <span className="btn-label">Birinchi loyiha</span>
            </Link>
          </EmptyState>
        )}

        {view !== null && view.entries.length > 0 && <LedgerRows view={view} />}
      </div>
    </AppChrome>
  );
}
