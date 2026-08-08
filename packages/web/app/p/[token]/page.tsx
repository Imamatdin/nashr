"use client";

// Public share view (P3 item 5): no auth, no session. The token IS the
// capability — the API resolves it server-side and returns a short-TTL
// signed URL; the raw project id never appears in this route.

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { type SharedDeckView, resolveSharedDeck } from "@/lib/api";

export default function SharedDeckPage() {
  const params = useParams<{ token: string }>();
  const [deck, setDeck] = useState<SharedDeckView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    resolveSharedDeck(params.token)
      .then(setDeck)
      .catch(() => setError("Havola topilmadi yoki bekor qilingan."));
  }, [params.token]);

  return (
    <main>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {!deck && !error && <p>Yuklanmoqda…</p>}
      {deck && (
        <>
          <h1>{deck.title}</h1>
          <iframe
            src={deck.html_url}
            sandbox="allow-scripts"
            style={{ width: "100%", aspectRatio: "16 / 9", border: "1px solid #ccc" }}
            title={deck.title}
          />
        </>
      )}
    </main>
  );
}
