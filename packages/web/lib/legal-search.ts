import type { Locale } from "./locale";

/** Build an outbound Lex.uz title search without copying its result set. */
export function lexUzSearchUrl(query: string, locale: Locale): string {
  const title = query.trim().slice(0, 100);
  const base = `https://lex.uz/${locale}/search/all`;
  if (title.length < 3) return `https://lex.uz/${locale}/`;
  return `${base}?${new URLSearchParams({ searchtitle: title }).toString()}`;
}
