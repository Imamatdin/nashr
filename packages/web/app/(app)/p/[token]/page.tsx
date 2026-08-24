"use client";

// Public share view (P3 item 5): no auth, no session. The token IS the
// capability — the API resolves it server-side and returns a short-TTL signed
// URL; the raw project id never appears in this route. The viewer is the
// product side of the split (spec §2), so this page renders dark like the deck
// it frames, forced with .dark on its own root regardless of visitor theme.
//
// What a recipient gets is the deck itself, not a picture of it: the same
// PPTX/PDF the owner can download, because the token already grants the whole
// deck (G19). Everything the page says about lifetimes and failures comes from
// lib/share-link.ts — the two facts the old view stated wrongly.

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ErrorState } from "@/components/ui";
import { type SharedDeckView, resolveSharedDeck } from "@/lib/api";
import {
  LINK_LIFETIME_CAPTION,
  type ShareFailure,
  classifyShareFailure,
  downloadFreshnessNote,
} from "@/lib/share-link";
import "../../doors.css";

export default function SharedDeckPage() {
  const params = useParams<{ token: string }>();
  const [deck, setDeck] = useState<SharedDeckView | null>(null);
  const [failure, setFailure] = useState<ShareFailure | null>(null);
  const [loading, setLoading] = useState(true);
  // The AUTOMATIC re-mint fires at most once: a frame that fails for any other
  // reason would otherwise reload forever. The manual control below is not
  // latched — a viewer who presses it means it (G20).
  const reminted = useRef(false);

  const load = useCallback(() => {
    setFailure(null);
    setLoading(true);
    resolveSharedDeck(params.token)
      .then((view) => {
        setDeck(view);
        setLoading(false);
      })
      .catch((error: unknown) => {
        setFailure(classifyShareFailure(error));
        setLoading(false);
      });
  }, [params.token]);

  useEffect(() => {
    load();
  }, [load]);

  const remint = useCallback(() => {
    if (reminted.current) return;
    reminted.current = true;
    load();
  }, [load]);

  const returnTo = `/login?returnTo=${encodeURIComponent(`/p/${params.token}`)}`;

  return (
    <div className="dark share-shell">
      <header className="share-top">
        <Link href="/" className="share-wordmark">
          Nashr
        </Link>
        {deck && <span className="share-doc">{deck.title}</span>}
      </header>

      <main className="share-main">
        <div className="share-stage">
          {failure && (
            <div className="share-error">
              <ErrorState
                title={failure.title}
                message={failure.message}
                // A retry button on a missing or rotated link is a lie: the
                // token will be just as absent on the second press.
                onRetry={failure.retryable ? load : undefined}
              />
              {failure.detail && (
                <details className="share-detail">
                  <summary>Texnik tafsilot</summary>
                  <code>{failure.detail}</code>
                </details>
              )}
            </div>
          )}

          {loading && !failure && (
            <>
              <div
                className="skeleton"
                style={{ height: "1.1rem", width: "40%", marginBottom: "12px" }}
              />
              <div className="skeleton share-frame" />
              <p className="share-caption" role="status">
                TAQDIMOT OCHILMOQDA…
              </p>
            </>
          )}

          {deck && !loading && !failure && (
            <>
              <div className="share-frame">
                <iframe
                  src={deck.html_url}
                  sandbox="allow-scripts"
                  title={deck.title}
                  // Fires for a genuine network failure, NOT for an HTTP
                  // error inside the frame: R2 serves its own body and the
                  // frame counts as loaded. So this is a bonus path, not the
                  // guarantee — the visible control below is the real recovery.
                  onError={remint}
                />
              </div>

              <p className="share-refresh">
                Slaydlar ochilmayaptimi?{" "}
                <button type="button" className="share-refresh-btn" onClick={load}>
                  Yangilash
                </button>
              </p>

              <div className="share-take">
                {deck.downloads.length > 0 ? (
                  <>
                    <div className="share-actions">
                      {deck.downloads.map((download) => (
                        <a
                          key={download.format}
                          href={download.url}
                          download
                          className="btn btn-ghost share-download"
                        >
                          <span className="btn-label">{download.format.toUpperCase()}</span>
                        </a>
                      ))}
                      <a
                        href={deck.html_url}
                        target="_blank"
                        rel="noreferrer"
                        className="btn btn-ghost share-download"
                      >
                        <span className="btn-label">To&rsquo;liq ekran</span>
                      </a>
                    </div>
                    <p className="share-fine">
                      {downloadFreshnessNote(deck.downloads[0].expires_in)}
                    </p>
                  </>
                ) : (
                  <p className="share-fine">
                    Yuklab olinadigan fayllar hali tayyorlanmoqda. Birozdan so&rsquo;ng
                    sahifani yangilang.
                  </p>
                )}
              </div>

              <p className="share-caption">{LINK_LIFETIME_CAPTION}</p>
            </>
          )}
        </div>
      </main>

      <footer className="share-foot">
        <Link href="/" className="share-made">
          <span className="share-made-mark" aria-hidden>
            N
          </span>
          Nashr bilan tayyorlandi
        </Link>
        {/* returnTo carries the visitor back to this deck after signing up,
            instead of dropping them on an empty folio. */}
        <Link href={returnTo} className="btn btn-primary">
          O&rsquo;zingiznikini yarating
        </Link>
      </footer>
    </div>
  );
}
