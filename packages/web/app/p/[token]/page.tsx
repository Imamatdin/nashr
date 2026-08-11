"use client";

// Public share view (P3 item 5, restyled P3.5): no auth, no session. The
// token IS the capability — the API resolves it server-side and returns a
// short-TTL signed URL; the raw project id never appears in this route.
// This page doubles as marketing: viewer chrome + "Made with Nashr" footer.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ErrorState, Skeleton } from "@/components/ui";
import { type SharedDeckView, resolveSharedDeck } from "@/lib/api";

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
    <div className="share-shell">
      <header className="topbar">
        <div className="container topbar-inner">
          <Link href="/" className="wordmark">
            Nashr
          </Link>
          {deck && (
            <span
              style={{
                fontWeight: 700,
                fontSize: "var(--text-sm)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {deck.title}
            </span>
          )}
        </div>
      </header>

      <main className="share-main">
        {error && (
          <div className="card" style={{ marginTop: "var(--sp-6)" }}>
            <ErrorState title="Taqdimot ochilmadi" message={error} onRetry={load} />
          </div>
        )}
        {!deck && !error && (
          <div className="viewer-chrome" style={{ marginTop: "var(--sp-5)" }}>
            <Skeleton lines={1} />
            <div className="skeleton" style={{ aspectRatio: "16 / 9", marginTop: "var(--sp-3)" }} />
          </div>
        )}
        {deck && (
          <div className="viewer-chrome" style={{ marginTop: "var(--sp-5)" }}>
            <iframe className="viewer-frame" src={deck.html_url} sandbox="allow-scripts" title={deck.title} />
          </div>
        )}
      </main>

      <footer className="footer">
        <div className="container footer-inner">
          <Link href="/" className="made-with">
            <span
              aria-hidden
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: "var(--gold)",
                display: "inline-block",
              }}
            />
            Nashr bilan tayyorlandi
          </Link>
          <Link href="/login" style={{ fontSize: "var(--text-sm)", fontWeight: 600 }}>
            O'zingiznikini yarating →
          </Link>
        </div>
      </footer>
    </div>
  );
}
