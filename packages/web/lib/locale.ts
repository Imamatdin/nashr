export const LOCALES = ["uz", "ru", "kaa", "en"] as const;
export type Locale = (typeof LOCALES)[number];
export const LOCALE_NAMES: Record<Locale, string> = {
  uz: "O‘zbekcha",
  ru: "Русский",
  kaa: "Qaraqalpaqsha",
  en: "English",
};
export const LOCALE_KEY = "nashr.locale";

export function resolveLocale(saved: string | null, browser = "uz"): Locale {
  if (LOCALES.includes(saved as Locale)) return saved as Locale;
  const language = browser.toLowerCase().split("-")[0];
  return LOCALES.includes(language as Locale) ? language as Locale : "uz";
}

/** Bound the decoded return path, including the encoded Cyrillic brief. */
export function creationHref(locale: Locale, topic = ""): string {
  let brief = topic.trim().slice(0, 200);
  const target = () => `/new?lang=${locale}${brief ? `&topic=${encodeURIComponent(brief)}` : ""}`;
  while (target().length > 480) brief = Array.from(brief).slice(0, -1).join("");
  return `/login?returnTo=${encodeURIComponent(target())}`;
}
