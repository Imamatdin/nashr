"use client";

// Public share view (P3 item 5, restyled P3.5): no auth, no session. The
// token IS the capability — the API resolves it server-side and returns a
// short-TTL signed URL; the raw project id never appears in this route.
// This page doubles as marketing: viewer chrome + "Made with Nashr" footer.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { DataText, ErrorState, Skeleton } from "@/components/ui";
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
    // §2 of the direction: the viewer is the product side of the split, so the
    // share page reads paper-on-ink like the deck it frames. The colour is
    // restated here because body's foreground resolves outside this subtree.
    <div className="dark share-shell" style={{ color: "var(--foreground)" }}>
      <header className="topbar">
        <div className="container topbar-inner">
          <Link href="/" className="wordmark">
            Nashr
          </Link>
          {deck && (
            <span
              // At 390 the ellipsised title runs right up against the
              // wordmark; the gap keeps the two as separate objects, and
              // min-width:0 is what actually lets the ellipsis engage.
              style={{
                fontWeight: 700,
                fontSize: "var(--text-sm)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                marginLeft: "var(--sp-4)",
                minWidth: 0,
              }}
            >
              {deck.title}
            </span>
          )}
        </div>
      </header>

      {/* The three states share one frame and one optical centre: top-aligning
          a 16:9 plate left ~600px of dead ground beneath it at both widths. */}
      <main
        className="share-main"
        style={{ display: "flex", flexDirection: "column", justifyContent: "center" }}
      >
        {error && (
          <div className="viewer-chrome" style={{ maxWidth: "560px", margin: "0 auto", width: "100%" }}>
            <ErrorState title="Taqdimot ochilmadi" message={error} onRetry={load} />
          </div>
        )}
        {!deck && !error && (
          <div className="viewer-chrome">
            <Skeleton lines={1} />
            <div className="skeleton" style={{ aspectRatio: "16 / 9", marginTop: "var(--sp-3)" }} />
          </div>
        )}
        {deck && (
          <div className="viewer-chrome">
            <iframe className="viewer-frame" src={deck.html_url} sandbox="allow-scripts" title={deck.title} />
            {/* The frame becomes a plate: the landing's mono caption carries
                the one machine fact this route already fetched and threw away.
                Days are computed, never asserted — a share link that says 7
                when it has 2 left is exactly the unsourced claim we refuse. */}
            <figcaption className="plate-caption">
              NASHR BILAN BOSILDI — HAVOLA{" "}
              <DataText>{Math.ceil(deck.expires_in / 86400)}</DataText> KUNDAN
              KEYIN YOPILADI
            </figcaption>
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
          {/* The one ask on this page, so it takes the press object rather
              than a bare anchor: hover/active/focus-visible come with it. */}
          <Link href="/login" className="btn btn-primary">
            O&rsquo;zingiznikini yarating →
          </Link>
        </div>
      </footer>
    </div>
  );
}
