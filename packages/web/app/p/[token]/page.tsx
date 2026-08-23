"use client";

// Public share view (P3 item 5): no auth, no session. The token IS the
// capability — the API resolves it server-side and returns a short-TTL signed
// URL; the raw project id never appears in this route. The viewer is the
// product side of the split (spec §2), so this page renders dark like the deck
// it frames, forced with .dark on its own root regardless of visitor theme.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { DataText, ErrorState, Skeleton } from "@/components/ui";
import { type SharedDeckView, resolveSharedDeck } from "@/lib/api";
import "../../doors.css";

export default function SharedDeckPage() {
  const params = useParams<{ token: string }>();
  const [deck, setDeck] = useState<SharedDeckView | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    resolveSharedDeck(params.token)
      .then(setDeck)
      .catch(() => setError("Havola topilmadi yoki bekor qilingan."));
  }, [params.token]);

  useEffect(() => {
    load();
  }, [load]);

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
          {error && (
            <div className="share-error">
              <ErrorState title="Taqdimot ochilmadi" message={error} onRetry={load} />
            </div>
          )}

          {!deck && !error && (
            <>
              <div
                className="skeleton"
                style={{ height: "1.1rem", width: "40%", marginBottom: "12px" }}
              />
              <div className="skeleton share-frame" />
            </>
          )}

          {deck && (
            <>
              <div className="share-frame">
                <iframe src={deck.html_url} sandbox="allow-scripts" title={deck.title} />
              </div>
              {/* Days are computed, never asserted — a share link that claims 7
                  when it has 2 left is exactly the unsourced claim Nashr refuses. */}
              <p className="share-caption">
                NASHR BILAN BOSILDI · HAVOLA{" "}
                <DataText>{Math.ceil(deck.expires_in / 86400)}</DataText> KUNDAN KEYIN YOPILADI
              </p>
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
        <Link href="/login" className="btn btn-primary">
          O&rsquo;zingiznikini yarating
        </Link>
      </footer>
    </div>
  );
}
